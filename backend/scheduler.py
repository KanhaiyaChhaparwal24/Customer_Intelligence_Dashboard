"""
scheduler.py
APScheduler setup.
- Runs sync_all() immediately on startup
- Repeats every SYNC_INTERVAL_MINUTES
"""
import asyncio
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from config import SYNC_INTERVAL_MINUTES

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def _run_sync():
    """Wrapper to run async sync in the background scheduler thread."""
    try:
        from services.sync_service import sync_all
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(sync_all())
        loop.close()
        logger.info(f"Scheduled sync result: {result.get('status')}")
    except Exception as e:
        logger.error(f"Scheduled sync error: {e}")


def _on_job_event(event):
    if event.exception:
        logger.error(f"Scheduler job failed: {event.exception}")
    else:
        logger.debug("Scheduler job completed successfully")


def start_scheduler():
    scheduler.add_listener(_on_job_event, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)

    # Run immediately on startup
    scheduler.add_job(
        _run_sync,
        id="initial_sync",
        name="Initial Sync on Startup",
        next_run_time=__import__("datetime").datetime.now(),
    )

    # Then every N minutes
    scheduler.add_job(
        _run_sync,
        "interval",
        minutes=SYNC_INTERVAL_MINUTES,
        id="periodic_sync",
        name=f"Periodic Sync (every {SYNC_INTERVAL_MINUTES} min)",
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    logger.info(
        f"Scheduler started — immediate sync triggered, "
        f"then every {SYNC_INTERVAL_MINUTES} minutes"
    )


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
