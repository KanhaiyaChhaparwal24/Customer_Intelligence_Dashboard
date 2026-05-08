"""
scheduler.py
APScheduler setup with overlap prevention and timeout.
- Runs sync_all() immediately on startup
- Repeats every SYNC_INTERVAL_MINUTES
- Prevents overlapping jobs (skips if previous still running)
- Enforces timeout to kill hung syncs
"""
import asyncio
import logging
import time
from datetime import datetime
from threading import Lock
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from config import SYNC_INTERVAL_MINUTES, SYNC_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()

# ── Sync state tracking ──────────────────────────────────────────────────
_sync_state_lock = Lock()
_sync_running: bool = False
_sync_start_time: float = 0
_sync_last_result: dict = {}


def _run_sync():
    """
    Wrapper to run async sync in the background scheduler thread.
    Prevents overlapping jobs and enforces timeout.
    """
    global _sync_running, _sync_start_time, _sync_last_result
    
    with _sync_state_lock:
        # Check if already running
        if _sync_running:
            elapsed = time.time() - _sync_start_time
            if elapsed > SYNC_TIMEOUT_SECONDS:
                # Previous sync exceeded timeout — force kill and restart
                logger.warning(
                    f"Previous sync exceeded timeout ({elapsed:.0f}s > {SYNC_TIMEOUT_SECONDS}s). "
                    f"Marking as stale and restarting."
                )
                _sync_running = False
                _sync_last_result = {
                    "status": "timeout",
                    "error": f"Previous sync exceeded {SYNC_TIMEOUT_SECONDS}s timeout",
                    "recovery": "restarted"
                }
            else:
                # Still within timeout window — skip this cycle
                logger.info(
                    f"Sync already running ({elapsed:.0f}s elapsed). Skipping this cycle."
                )
                return
        
        _sync_running = True
        _sync_start_time = time.time()
    
    try:
        from services.sync_service import sync_all
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run with timeout enforcement
        try:
            result = loop.run_until_complete(
                asyncio.wait_for(sync_all(), timeout=SYNC_TIMEOUT_SECONDS)
            )
            logger.info(f"Scheduled sync result: {result.get('status')}")
            _sync_last_result = result
        except asyncio.TimeoutError:
            logger.error(f"Sync exceeded {SYNC_TIMEOUT_SECONDS}s timeout")
            _sync_last_result = {
                "status": "timeout",
                "error": f"Sync execution exceeded {SYNC_TIMEOUT_SECONDS}s",
                "duration_seconds": time.time() - _sync_start_time
            }
        
        loop.close()
    except Exception as e:
        logger.error(f"Scheduled sync error: {e}")
        _sync_last_result = {
            "status": "failed",
            "error": str(e),
            "duration_seconds": time.time() - _sync_start_time
        }
    finally:
        with _sync_state_lock:
            _sync_running = False


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
        f"then every {SYNC_INTERVAL_MINUTES} minutes (timeout: {SYNC_TIMEOUT_SECONDS}s)"
    )


def get_sync_state() -> dict:
    """Return current sync state (for dashboard status)."""
    global _sync_running, _sync_start_time, _sync_last_result
    with _sync_state_lock:
        if _sync_running:
            elapsed = time.time() - _sync_start_time
            return {
                "is_running": True,
                "elapsed_seconds": round(elapsed, 2),
                "will_timeout_in_seconds": max(0, round(SYNC_TIMEOUT_SECONDS - elapsed, 2)),
                "status": "running",
            }
        else:
            return {
                "is_running": False,
                "status": _sync_last_result.get("status", "idle"),
                "last_result": _sync_last_result,
            }


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
