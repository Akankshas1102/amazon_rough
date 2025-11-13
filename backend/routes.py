# backend/routes.py

from fastapi import APIRouter, HTTPException, Query
from services import device_service, proevent_service, cache_service
from models import (DeviceOut, DeviceActionRequest, DeviceActionSummaryResponse,
                   BuildingOut, BuildingTimeRequest, BuildingTimeResponse,
                   IgnoredItemRequest, IgnoredItemBulkRequest,
                   PanelStatus)
from sqlite_config import (get_building_time, set_building_time,
                           get_ignored_proevents, set_proevent_ignore_status,
                           get_all_building_times)
from logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# --- Panel Status Endpoints ---

@router.get("/panel_status", response_model=PanelStatus)
def get_panel_status():
    logger.debug("GET /panel_status called")
    status = cache_service.get_cache_value('panel_armed')
    if status is None:
        status = True
        cache_service.set_cache_value('panel_armed', status)
    logger.info(f"Panel status retrieved: {'Armed' if status else 'Disarmed'}")
    return PanelStatus(armed=status)

@router.post("/panel_status", response_model=PanelStatus)
def set_panel_status(status: PanelStatus):
    logger.info(f"POST /panel_status called with status: {'Armed' if status.armed else 'Disarmed'}")
    cache_service.set_cache_value('panel_armed', status.armed)
    logger.info(f"✅ Global panel status set to: {'Armed' if status.armed else 'Disarmed'}")
    return status


# --- Building and Device Routes ---

@router.get("/buildings", response_model=list[BuildingOut])
def list_buildings():
    """
    Fetches real buildings from PROD DB and merges schedules from SQLite DB.
    """
    logger.info("GET /buildings called - Fetching all buildings...")
    try:
        buildings_from_db = device_service.get_distinct_buildings()
        logger.debug(f"Retrieved {len(buildings_from_db)} buildings from database")
        
        schedules_from_sqlite = get_all_building_times()
        logger.debug(f"Retrieved schedules for {len(schedules_from_sqlite)} buildings from SQLite")
        
        buildings_out = []
        for b in buildings_from_db:
            building_id = b["id"]
            schedule = schedules_from_sqlite.get(building_id)
            start_time = schedule.get("start_time", "20:00") if schedule else "20:00"

            buildings_out.append(BuildingOut(
                id=building_id,
                name=b["name"],
                start_time=start_time
            ))
        
        logger.info(f"✅ Returning {len(buildings_out)} buildings")
        return buildings_out
    except Exception as e:
        logger.error(f"❌ Error in list_buildings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/devices", response_model=list[DeviceOut])
def list_proevents(
    building: int | None = Query(default=None),
    search: str | None = Query(default=""),
    limit: int = Query(default=100, ge=1, le=10000),
    offset: int = Query(default=0, ge=0)
):
    """
    Fetches real devices (proevents) from PROD DB and merges
    ignore status from SQLite DB.
    """
    logger.info(f"GET /devices called - building={building}, search='{search}', limit={limit}, offset={offset}")
    
    if building is None:
        logger.warning("Building ID is required but not provided")
        raise HTTPException(status_code=400, detail="A building ID is required.")
    
    try:
        logger.debug(f"Fetching proevents for building {building}...")
        proevents = proevent_service.get_all_proevents_for_building(
            building_id=building, search=search, limit=limit, offset=offset
        )
        logger.debug(f"Retrieved {len(proevents)} proevents")
        
        ignored_proevents = get_ignored_proevents()
        logger.debug(f"Retrieved {len(ignored_proevents)} ignored proevents from SQLite")
        
        proevents_out = []
        
        for p in proevents:
            ignore_status = ignored_proevents.get(p["id"], {})
            state_str = "armed" if p["reactive_state"] == 0 else "disarmed"
            
            proevent_out = DeviceOut(
                id=p["id"],
                name=p["name"],
                state=state_str,
                building_name=p.get("building_name", ""),
                is_ignored=ignore_status.get("ignore_on_disarm", False)
            )
            proevents_out.append(proevent_out)

        logger.info(f"✅ Returning {len(proevents_out)} devices for building {building}")
        return proevents_out
    except Exception as e:
        logger.error(f"❌ Error in list_proevents for building {building}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# --- Schedule and Ignore Endpoints ---

@router.get("/buildings/{building_id}/time")
def get_building_scheduled_time(building_id: int):
    logger.info(f"GET /buildings/{building_id}/time called")
    try:
        times = get_building_time(building_id)
        result = {
            "building_id": building_id,
            "start_time": times.get("start_time") if times else None
        }
        logger.debug(f"Building {building_id} schedule: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ Error getting building time for {building_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/buildings/{building_id}/time", response_model=BuildingTimeResponse)
def set_building_scheduled_time(building_id: int, request: BuildingTimeRequest):
    logger.info(f"POST /buildings/{building_id}/time called with start_time={request.start_time}")
    
    if request.building_id != building_id:
        logger.warning(f"Building ID mismatch: path={building_id}, body={request.building_id}")
        raise HTTPException(400, "Building ID in path and body must match")
    
    try:
        success = set_building_time(building_id, request.start_time)
        if not success:
            logger.error(f"Failed to update building scheduled time for {building_id}")
            raise HTTPException(500, "Failed to update building scheduled time")
        
        logger.info(f"✅ Building {building_id} schedule updated to start_time={request.start_time}")
        return BuildingTimeResponse(
            building_id=building_id,
            start_time=request.start_time,
            updated=True
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error setting building time for {building_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/buildings/{building_id}/reevaluate")
def reevaluate_building(building_id: int):
    """
    Triggers scheduler logic for one building immediately.
    """
    logger.info(f"POST /buildings/{building_id}/reevaluate called")
    try:
        proevent_service.reevaluate_building_state(building_id)
        logger.info(f"✅ Building {building_id} re-evaluated successfully")
        return {"status": "success", "message": f"Building {building_id} re-evaluated."}
    except Exception as e:
        logger.error(f"❌ Failed to re-evaluate building {building_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to re-evaluate building: {e}")


@router.post("/proevents/ignore/bulk")
def manage_ignored_proevents_bulk(req: IgnoredItemBulkRequest):
    """
    Saves the ignore list to the local SQLite DB.
    """
    logger.info(f"POST /proevents/ignore/bulk called with {len(req.items)} items")
    try:
        for item in req.items:
            logger.debug(f"Setting ignore status for proevent {item.item_id}: ignore={item.ignore}")
            set_proevent_ignore_status(
                item.item_id, item.building_frk, item.device_prk, 
                ignore_on_arm=False,
                ignore_on_disarm=item.ignore
            )
        logger.info(f"✅ Successfully saved ignore status for {len(req.items)} proevents")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"❌ Error saving ignore bulk: {e}", exc_info=True)
        raise HTTPException(500, "Failed to save ignore status")


# --- Legacy Endpoint ---

@router.post("/devices/action", response_model=DeviceActionSummaryResponse)
def device_action(req: DeviceActionRequest):
    """
    Legacy endpoint - not used by frontend.
    """
    logger.warning(f"Legacy endpoint /devices/action called for building {req.building_id} with action={req.action}")
    
    reactive_state = 1 if req.action.lower() == "disarm" else 0
    
    try:
        affected_rows = proevent_service.set_proevent_reactive_for_building(
            req.building_id, reactive_state, []
        )
        logger.info(f"Legacy action completed: {affected_rows} rows affected")
        return DeviceActionSummaryResponse(
            success_count=affected_rows,
            failure_count=0,
            details=[]
        )
    except Exception as e:
        logger.error(f"❌ Error during legacy bulk action for building {req.building_id}: {e}", exc_info=True)
        raise HTTPException(500, str(e))