# backend/services/proevent_service.py

from services import proserver_service, device_service, cache_service
import sqlite_config
import pytz
from datetime import datetime
from logger import get_logger

logger = get_logger(__name__)

# --- EXISTING FUNCTIONS ---

def get_all_proevents_for_building(building_id: int, search: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
    """
    Gets all proevents for a building, enriched with their reactive state.
    """
    try:
        devices = device_service.get_devices(
            building_id=building_id, search=search, limit=limit, offset=offset
        )
        if not devices:
            return []
        
        return devices
        
    except Exception as e:
        logger.error(f"Error getting proevents for building {building_id}: {e}")
        return []

def set_proevent_reactive_for_building(building_id: int, reactive: int, ignore_ids: list[int] | None = None) -> int:
    """
    Sets the reactive state for all proevents in a building,
    skipping any IDs in the ignore_ids list.
    """
    if ignore_ids is None:
        ignore_ids = []
    
    logger.info(f"Setting reactive state to {reactive} for building {building_id}, ignoring {len(ignore_ids)} IDs.")
    
    try:
        devices = device_service.get_devices(building_id=building_id, limit=1000)
        if not devices:
            logger.warning(f"No devices found for building {building_id}, nothing to update.")
            return 0
            
        proevent_ids_to_update = [
            d["id"] for d in devices if d["id"] not in ignore_ids
        ]

        if not proevent_ids_to_update:
            logger.info(f"All devices in building {building_id} were on the ignore list. No updates sent.")
            return 0

        target_states = [{"id": pid, "state": reactive} for pid in proevent_ids_to_update]
        success = proserver_service.set_proevent_reactive_state_bulk(target_states)
        
        return len(proevent_ids_to_update) if success else 0
        
    except Exception as e:
        logger.error(f"Error in set_proevent_reactive_for_building (Building {building_id}): {e}")
        return 0

def manage_proevents_on_panel_state_change():
    """
    Monitors panel state changes and manages ProEvent reactive states accordingly.
    """
    try:
        live_states = proserver_service.get_all_live_building_arm_states()
        cached_states = cache_service.get_cache_value("panel_state_cache") or {}
        new_cached_states = cached_states.copy()

        for building_id, is_armed in live_states.items():
            prev_state = cached_states.get(str(building_id))

            if prev_state is None:
                new_cached_states[str(building_id)] = is_armed
                continue

            if prev_state == is_armed:
                continue

            logger.info(f"[Building {building_id}] Panel state changed -> {'ARMED' if is_armed else 'DISARMED'}")

            all_proevents = proserver_service.get_proevents_for_building_from_db(building_id)
            if not all_proevents:
                logger.warning(f"[Building {building_id}] No ProEvents found in DB.")
                new_cached_states[str(building_id)] = is_armed
                continue

            ignored_map = sqlite_config.get_ignored_proevents()
            ignored_ids = {
                pid for pid, data in ignored_map.items()
                if data.get("building_frk") == building_id and data.get("ignore_on_disarm")
            }

            if is_armed:
                if ignored_ids:
                    target_states = [{"id": pid, "state": 0} for pid in ignored_ids]
                    success = proserver_service.set_proevent_reactive_state_bulk(target_states)
                    if success:
                        logger.info(f"[Building {building_id}] Panel ARMED -> {len(target_states)} previously ignored ProEvents set Reactive.")
                    else:
                        logger.error(f"[Building {building_id}] Failed to reactivate previously ignored ProEvents.")
                else:
                    logger.info(f"[Building {building_id}] Panel ARMED -> No previously ignored ProEvents to change.")

                new_cached_states[str(building_id)] = is_armed
                continue

            if not is_armed and ignored_ids:
                target_states = [{"id": pid, "state": 1} for pid in ignored_ids]
                success = proserver_service.set_proevent_reactive_state_bulk(target_states)
                if success:
                    logger.info(f"[Building {building_id}] Panel DISARMED -> {len(target_states)} selected ProEvents set Non-Reactive.")
                else:
                    logger.error(f"[Building {building_id}] Failed to disarm selected ProEvents.")
            else:
                logger.info(f"[Building {building_id}] Panel DISARMED -> No ignored ProEvents to change.")

            new_cached_states[str(building_id)] = is_armed

        cache_service.set_cache_value("panel_state_cache", new_cached_states)

    except Exception as e:
        logger.error(f"Error in manage_proevents_on_panel_state_change: {e}")

def manage_proevents_on_panel_state_change():
    """
    Fixed logic (final):
    ---------------------
    - When panel is Armed   -> Make ONLY previously ignored (UI-selected) ProEvents Reactive (0)
    - When panel is Disarmed -> Make ONLY ignored (UI-selected) ProEvents Non-Reactive (1)
    - Cache ensures it runs only on state change
    """
    try:
        live_states = proserver_service.get_all_live_building_arm_states()
        cached_states = cache_service.get_cache_value("panel_state_cache") or {}
        new_cached_states = cached_states.copy()

        for building_id, is_armed in live_states.items():
            prev_state = cached_states.get(str(building_id))
            logger.info(f"[DEBUG] Building {building_id}: current={is_armed}, previous={prev_state}")

            # First run → store and continue
            if prev_state is None:
                new_cached_states[str(building_id)] = is_armed
                continue

            # No change → skip
            if prev_state == is_armed:
                continue

            # Panel state changed
            logger.info(f"[Building {building_id}] Panel state changed -> {'ARMED' if is_armed else 'DISARMED'}")

            # Fetch all ProEvents for this building
            all_proevents = proserver_service.get_proevents_for_building_from_db(building_id)
            if not all_proevents:
                logger.warning(f"[Building {building_id}] No ProEvents found in DB.")
                new_cached_states[str(building_id)] = is_armed
                continue

            # Load ignored ProEvents from SQLite (UI selections)
            ignored_map = sqlite_config.get_ignored_proevents()
            ignored_ids = {
                pid for pid, data in ignored_map.items()
                if data.get("building_frk") == building_id and data.get("ignore_on_disarm")
            }

            # When Armed → only previously ignored become Reactive again
            if is_armed:
                if ignored_ids:
                    target_states = [{"id": pid, "state": 0} for pid in ignored_ids]
                    success = proserver_service.set_proevent_reactive_state_bulk(target_states)
                    if success:
                        logger.info(f"[Building {building_id}] Panel ARMED -> {len(target_states)} previously ignored ProEvents set Reactive.")
                    else:
                        logger.error(f"[Building {building_id}] Failed to reactivate previously ignored ProEvents.")
                else:
                    logger.info(f"[Building {building_id}] Panel ARMED -> No previously ignored ProEvents to change.")

                new_cached_states[str(building_id)] = is_armed
                continue

            # When Disarmed → only ignored ones become Non-Reactive
            if not is_armed and ignored_ids:
                target_states = [{"id": pid, "state": 1} for pid in ignored_ids]
                success = proserver_service.set_proevent_reactive_state_bulk(target_states)
                if success:
                    logger.info(f"[Building {building_id}] Panel DISARMED -> {len(target_states)} selected ProEvents set Non-Reactive.")
                else:
                    logger.error(f"[Building {building_id}] Failed to disarm selected ProEvents.")
            else:
                logger.info(f"[Building {building_id}] Panel DISARMED -> No ignored ProEvents to change.")

            new_cached_states[str(building_id)] = is_armed

        # Update cache
        cache_service.set_cache_value("panel_state_cache", new_cached_states)

    except Exception as e:
        logger.error(f"Error in manage_proevents_on_panel_state_change: {e}")


def check_and_manage_scheduled_states():
    """
    Checks if current time matches building start_time and sends alert if panel is disarmed.
    """
    import logging

    try:
        tz = pytz.timezone('Asia/Kolkata')
        current_time = datetime.now(tz).strftime("%H:%M")
        live_building_arm_states = proserver_service.get_all_live_building_arm_states()

        for building_id, is_armed in live_building_arm_states.items():
            schedule = sqlite_config.get_building_time(building_id)
            if not schedule:
                continue

            start_time = (schedule.get("start_time") or "20:00")[:5]

            if current_time != start_time:
                continue

            if is_armed:
                logging.info(f"[Building {building_id}] Panel ARMED at start time {start_time}. No alert sent.")
            else:
                logging.warning(f"[Building {building_id}] Panel DISARMED at start time {start_time}. Sending AXE alert.")
                proserver_service.send_disarmed_axe_message(building_id)

    except Exception as e:
        logging.error(f"Error in scheduled check_and_manage_scheduled_states: {e}")


def reevaluate_building_state(building_id: int):
    """
    Triggers an immediate re-evaluation of a single building's state.
    """
    try:
        is_panel_armed = cache_service.get_cache_value('panel_armed')
        if is_panel_armed:
            logger.warning(f"Manual re-evaluation for building {building_id} skipped: Panel is ARMED.")
            return

        logger.info(f"Manual re-evaluation triggered for building {building_id}.")
        _evaluate_building_state(building_id)
    except Exception as e:
        logger.error(f"Error in reevaluate_building_state (Building {building_id}): {e}")
        raise


def get_selected_proevents(building_id):
    """Fetch list of ProEvent IDs selected from frontend UI for this building."""
    try:
        conn = sqlite_config()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT speProEvent_FRK
            FROM SelectedProEvents_TBL
            WHERE speBuilding_FRK = ?
        """, building_id)
        result = [row[0] for row in cursor.fetchall()]
        conn.close()
        return result
    except Exception as e:
        logger.error(f"[ERROR] Failed to fetch selected proevents for building {building_id}: {e}")
        return []


def set_selected_proevents_nonreactive(building_id):
    """When panel disarms → make selected proevents non-reactive."""
    selected_ids = get_selected_proevents(building_id)
    if not selected_ids:
        logger.info(f"[INFO] No selected ProEvents to make non-reactive for building {building_id}.")
        return

    try:
        conn = ()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in selected_ids)
        query = f"""
            UPDATE ProEvent_TBL
            SET pevReactive_FRK = 0
            WHERE pevBuilding_FRK = ? AND ProEvent_PRK IN ({placeholders})
        """
        cursor.execute(query, building_id, *selected_ids)
        conn.commit()
        conn.close()
        logger.info(f"[ACTION] Set {len(selected_ids)} selected ProEvents non-reactive for building {building_id}.")
    except Exception as e:
        logger.error(f"[ERROR] Failed to make selected ProEvents non-reactive for building {building_id}: {e}")


def set_selected_proevents_reactive(building_id):
    """When panel arms → make only previously selected non-reactive proevents reactive again."""
    selected_ids = get_selected_proevents(building_id)
    if not selected_ids:
        logger.info(f"[INFO] No selected ProEvents to re-activate for building {building_id}.")
        return

    try:
        conn = sqlite_config()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in selected_ids)
        query = f"""
            UPDATE ProEvent_TBL
            SET pevReactive_FRK = 1
            WHERE pevBuilding_FRK = ? AND ProEvent_PRK IN ({placeholders})
        """
        cursor.execute(query, building_id, *selected_ids)
        conn.commit()
        conn.close()
        logger.info(f"[ACTION] Set {len(selected_ids)} selected ProEvents reactive again for building {building_id}.")
    except Exception as e:
        logger.error(f"[ERROR] Failed to re-activate selected ProEvents for building {building_id}: {e}")


# --- STATE MACHINE LOGIC ---

def _evaluate_building_state(building_id: int):
    """
    State machine logic for a single building - no end_time needed.
    """
    schedule = sqlite_config.get_building_time(building_id)
    if not schedule:
        return

    snapshot = sqlite_config.get_snapshot(building_id)
    snapshot_exists = (snapshot is not None)

    # If snapshot exists, just maintain current state
    if snapshot_exists:
        logger.info(f"[Building {building_id}]: Snapshot exists. Maintaining scheduled state.")
        pass
    else:
        # No snapshot means we haven't applied schedule yet
        logger.info(f"[Building {building_id}]: Taking snapshot and applying schedule...")
        take_snapshot_and_apply_schedule(building_id)


def take_snapshot_and_apply_schedule(building_id: int):
    """
    Takes snapshot and applies scheduled state.
    """
    try:
        all_devices_from_db = proserver_service.get_proevents_for_building_from_db(building_id)
        
        if not all_devices_from_db:
            logger.warning(f"Building {building_id}: No devices found in ProServer DB to snapshot.")
            return

        snapshot_data = [
            {"id": dev["id"], "state": dev["state"]} 
            for dev in all_devices_from_db
        ]
        
        sqlite_config.save_snapshot(building_id, snapshot_data)
        
        ignored_map = sqlite_config.get_ignored_proevents()
        ignored_ids = {
            pid for pid, data in ignored_map.items()
            if data.get("building_frk") == building_id and data.get("ignore_on_disarm")
        }
        
        target_states = []
        for device in snapshot_data:
            device_id = device['id']
            
            if device_id in ignored_ids:
                target_states.append({"id": device_id, "state": 1}) 
            else:
                target_states.append({"id": device_id, "state": 0})

        logger.info(f"[Building {building_id}]: Snapshot taken. Setting {len(ignored_ids)} devices to Non-Reactive (1) and {len(target_states) - len(ignored_ids)} to Reactive (0).")
        
        proserver_service.set_proevent_reactive_state_bulk(target_states)

    except Exception as e:
        logger.error(f"Failed to take snapshot for building {building_id}: {e}")

def revert_snapshot(building_id: int, snapshot_data: list[dict]):
    """
    Reverts devices to their original states from snapshot.
    """
    try:
        logger.info(f"[Building {building_id}]: Reverting {len(snapshot_data)} devices to their original states.")
        
        proserver_service.set_proevent_reactive_state_bulk(snapshot_data)
        sqlite_config.clear_snapshot(building_id)

    except Exception as e:
        logger.error(f"Failed to revert snapshot for building {building_id}: {e}")