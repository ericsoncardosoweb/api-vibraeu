"""
Background scheduler for processing interpretation queue.
Uses APScheduler for reliable job scheduling.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
from typing import Optional, Dict, Any
from loguru import logger
import asyncio

from config import get_settings


# Global scheduler instance
_scheduler: Optional[AsyncIOScheduler] = None
_is_running: bool = False
_last_run: Optional[datetime] = None
_last_result: Optional[Dict[str, Any]] = None
_startup_complete: bool = False


async def process_queue_job():
    """
    Background job that processes pending queue items.
    Called periodically by the scheduler.
    """
    global _last_run, _last_result, _startup_complete
    
    # Skip first run to allow application to fully initialize
    if not _startup_complete:
        _startup_complete = True
        logger.info("Scheduler: skipping first run (startup)")
        _last_result = {"success": True, "message": "Startup skip", "processed": 0}
        return
    
    _last_run = datetime.utcnow()
    logger.info("Scheduler job started")
    
    try:
        # Lazy import to avoid initialization issues
        from services.interpretation_service import InterpretationService
        
        settings = get_settings()
        service = InterpretationService()
        
        result = await service.process_pending(limit=settings.batch_size)
        
        _last_result = {
            "success": result["success"],
            "processed": result["processed"],
            "failed": result.get("failed", 0),
            "timestamp": _last_run.isoformat()
        }
        
        if result["processed"] > 0:
            logger.info(f"Scheduler processed {result['processed']} items")
            
    except Exception as e:
        logger.error(f"Scheduler job error: {e}")
        _last_result = {
            "success": False,
            "error": str(e),
            "timestamp": _last_run.isoformat() if _last_run else datetime.utcnow().isoformat()
        }
        # Don't re-raise - let scheduler continue running


def start_scheduler():
    """Start the background scheduler."""
    global _scheduler, _is_running
    
    if _scheduler is not None:
        logger.warning("Scheduler already started")
        return
    
    settings = get_settings()
    
    _scheduler = AsyncIOScheduler()
    
    # Add the processing job
    _scheduler.add_job(
        process_queue_job,
        trigger=IntervalTrigger(seconds=settings.scheduler_interval_seconds),
        id="process_queue",
        name="Process Interpretation Queue",
        replace_existing=True
    )
    
    _scheduler.start()
    _is_running = True
    
    logger.info(
        f"Scheduler started with {settings.scheduler_interval_seconds}s interval"
    )


def shutdown_scheduler():
    """Shutdown the scheduler gracefully."""
    global _scheduler, _is_running
    
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        _is_running = False
        logger.info("Scheduler shutdown complete")


def pause_scheduler():
    """Pause the scheduler."""
    global _scheduler, _is_running
    
    if _scheduler:
        _scheduler.pause()
        _is_running = False
        logger.info("Scheduler paused")


def resume_scheduler():
    """Resume the scheduler."""
    global _scheduler, _is_running
    
    if _scheduler:
        _scheduler.resume()
        _is_running = True
        logger.info("Scheduler resumed")


def get_scheduler_status() -> Dict[str, Any]:
    """Get current scheduler status."""
    global _scheduler, _is_running, _last_run, _last_result
    
    settings = get_settings()
    
    next_run = None
    if _scheduler:
        job = _scheduler.get_job("process_queue")
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()
    
    return {
        "enabled": settings.scheduler_enabled,
        "running": _is_running,
        "interval_seconds": settings.scheduler_interval_seconds,
        "next_run": next_run,
        "last_run": _last_run.isoformat() if _last_run else None,
        "last_result": _last_result
    }


async def run_scheduler_now() -> Dict[str, Any]:
    """Run the scheduler job immediately."""
    await process_queue_job()
    return _last_result or {"success": True, "message": "No result"}
