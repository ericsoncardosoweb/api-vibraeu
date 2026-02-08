"""
Scheduler endpoint - manage background scheduler.
"""

from fastapi import APIRouter
from loguru import logger

from scheduler.jobs import get_scheduler_status, run_scheduler_now, centelhas_replenish_job, suspend_inactive_free_accounts_job


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


@router.post("/replenish-centelhas")
async def replenish_centelhas():
    """
    Forçar recarga manual de centelhas para todos os usuários ativos.
    Útil para testes ou se o cron mensal não executou.
    """
    logger.info("Manual centelhas replenish triggered")
    await centelhas_replenish_job()
    return {"success": True, "message": "Centelhas replenish completed"}


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


@router.post("/suspend-inactive")
async def suspend_inactive():
    """
    Forçar suspensão manual de contas free inativas (30+ dias sem login).
    Útil para testes ou execução imediata.
    """
    logger.info("Manual inactive suspension triggered")
    await suspend_inactive_free_accounts_job()
    return {"success": True, "message": "Inactive accounts suspension completed"}
