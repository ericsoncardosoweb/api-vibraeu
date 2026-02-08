"""
Background scheduler for processing interpretation queue.
Uses APScheduler for reliable job scheduling.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
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


async def centelhas_replenish_job():
    """
    Recarga mensal de centelhas. Roda no 1° dia do mês às 03:00 UTC.
    Credita centelhas_mensais de cada plano para todos os usuários ativos.
    """
    logger.info("[Centelhas] Iniciando recarga mensal de centelhas...")
    
    try:
        from supabase import create_client
        settings = get_settings()
        
        supabase = create_client(settings.supabase_url, settings.supabase_service_key)
        
        # 1. Buscar planos com centelhas > 0
        planos_result = supabase.table("planos_config") \
            .select("id, centelhas_mensais") \
            .gt("centelhas_mensais", 0) \
            .eq("ativo", True) \
            .execute()
        
        if not planos_result.data:
            logger.info("[Centelhas] Nenhum plano com centelhas_mensais > 0")
            return
        
        planos_map = {p["id"]: p["centelhas_mensais"] for p in planos_result.data}
        logger.info(f"[Centelhas] Planos: {planos_map}")
        
        # 2. Para cada plano, buscar usuários ativos e creditar
        total_creditados = 0
        total_centelhas = 0
        
        for plano_id, centelhas_qty in planos_map.items():
            # Buscar profiles ativos neste plano
            profiles_result = supabase.table("profiles") \
                .select("id, centelhas, nome, email") \
                .eq("plano", plano_id) \
                .eq("subscription_status", "active") \
                .execute()
            
            if not profiles_result.data:
                logger.info(f"[Centelhas] Nenhum user ativo no plano {plano_id}")
                continue
            
            for profile in profiles_result.data:
                try:
                    centelhas_atuais = profile.get("centelhas", 0) or 0
                    novo_saldo = centelhas_atuais + centelhas_qty
                    
                    supabase.table("profiles").update({
                        "centelhas": novo_saldo,
                        "updated_at": datetime.utcnow().isoformat()
                    }).eq("id", profile["id"]).execute()
                    
                    total_creditados += 1
                    total_centelhas += centelhas_qty
                    logger.debug(f"[Centelhas] +{centelhas_qty} → {profile.get('email', profile['id'])} ({centelhas_atuais} → {novo_saldo})")
                    
                except Exception as e:
                    logger.error(f"[Centelhas] Erro ao creditar {profile['id']}: {e}")
        
        logger.info(f"[Centelhas] ✅ Recarga completa: {total_creditados} users, +{total_centelhas} centelhas total")
        
    except Exception as e:
        logger.error(f"[Centelhas] Erro na recarga mensal: {e}")


def start_scheduler():
    """Start the background scheduler."""
    global _scheduler, _is_running
    
    if _scheduler is not None:
        logger.warning("Scheduler already started")
        return
    
    settings = get_settings()
    
    _scheduler = AsyncIOScheduler()
    
    # Job 1: Processar fila de interpretações (intervalo configurável)
    _scheduler.add_job(
        process_queue_job,
        trigger=IntervalTrigger(seconds=settings.scheduler_interval_seconds),
        id="process_queue",
        name="Process Interpretation Queue",
        replace_existing=True
    )
    
    # Job 2: Recarga mensal de centelhas (dia 1 às 03:00 UTC)
    _scheduler.add_job(
        centelhas_replenish_job,
        trigger=CronTrigger(day=1, hour=3, minute=0),
        id="centelhas_replenish",
        name="Monthly Centelhas Replenish",
        replace_existing=True
    )
    
    _scheduler.start()
    _is_running = True
    
    logger.info(
        f"Scheduler started with {settings.scheduler_interval_seconds}s interval + monthly centelhas replenish"
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
