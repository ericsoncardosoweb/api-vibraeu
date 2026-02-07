"""
Scheduler endpoint - manage background scheduler.
"""

from fastapi import APIRouter
from loguru import logger

from scheduler.jobs import get_scheduler_status, run_scheduler_now


router = APIRouter()


@router.get("/status")
async def scheduler_status():
    """
    Get current scheduler status.
    
    Returns information about the scheduler state and next run time.
    """
    return get_scheduler_status()


@router.post("/run")
async def run_scheduler():
    """
    Manually trigger the scheduler to run now.
    
    Useful for testing or forcing immediate processing
    without waiting for the next scheduled run.
    """
    logger.info("Manual scheduler run triggered")
    
    result = await run_scheduler_now()
    
    return {
        "success": True,
        "message": "Scheduler run completed",
        **result
    }


@router.post("/pause")
async def pause_scheduler():
    """Pause the scheduler."""
    from scheduler.jobs import pause_scheduler as do_pause
    do_pause()
    return {"success": True, "message": "Scheduler paused"}


@router.post("/resume")
async def resume_scheduler():
    """Resume the scheduler."""
    from scheduler.jobs import resume_scheduler as do_resume
    do_resume()
    return {"success": True, "message": "Scheduler resumed"}
