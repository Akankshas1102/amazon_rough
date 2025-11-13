# backend/services/scheduler_service.py

import schedule
import time
import threading
from logger import get_logger
from services import proevent_service
import traceback

logger = get_logger(__name__)

def scheduled_job():
    """
    Main scheduler job that runs every minute.
    Phase 1: Check if building panel is disarmed at start time -> Send AXE alert.
    Phase 2: Detect panel ARM/DISARM transitions -> Toggle ProEvent reactive states.
    """
    logger.info("="*60)
    logger.info("🔄 Scheduler executing scheduled job...")
    logger.info("="*60)

    try:
        # Phase 1 – Scheduled AXE alert
        logger.info("Phase 1: Checking scheduled states and sending AXE alerts if needed...")
        proevent_service.check_and_manage_scheduled_states()
        logger.info("✅ Phase 1 completed")

        # Phase 2 – Continuous monitoring and ProEvent toggling
        logger.info("Phase 2: Managing ProEvents on panel state changes...")
        proevent_service.manage_proevents_on_panel_state_change()
        logger.info("✅ Phase 2 completed")
        
        logger.info("✅ Scheduled job completed successfully")
    except Exception as e:
        logger.error(f"❌ Error in scheduled job: {e}", exc_info=True)
        logger.error(f"Traceback: {traceback.format_exc()}")
    
    logger.info("="*60)


def run_scheduler():
    """
    Runs the scheduler in a separate thread.
    """
    logger.info("Scheduler thread started")
    schedule.every(1).minutes.do(scheduled_job)
    logger.info("Scheduled job registered to run every 1 minute")

    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            logger.error(f"❌ Error in scheduler loop: {e}", exc_info=True)
            time.sleep(5)  # Wait before retrying

def start_scheduler():
    """
    Starts the scheduler in a background thread.
    """
    logger.info("Starting scheduler in background thread...")
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    logger.info("✅ Scheduler thread started successfully")