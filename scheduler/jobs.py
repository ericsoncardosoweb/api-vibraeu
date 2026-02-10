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
import httpx

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


async def suspend_inactive_free_accounts_job():
    """
    Suspende contas free (semente) inativas há mais de 30 dias.
    Roda diariamente às 04:00 UTC.
    Usa auth.users.last_sign_in_at para determinar inatividade.
    Contas suspensas são reativadas automaticamente ao logar (ver AuthContext).
    """
    logger.info("[Suspend] Verificando contas free inativas...")
    
    try:
        from supabase import create_client
        from datetime import timedelta
        settings = get_settings()
        
        supabase = create_client(settings.supabase_url, settings.supabase_service_key)
        
        # 1. Buscar profiles free (semente) ativos ou sem status
        profiles_result = supabase.table("profiles") \
            .select("id, plano, subscription_status, nome, email") \
            .in_("plano", ["semente", "free", ""]) \
            .neq("subscription_status", "suspended") \
            .execute()
        
        if not profiles_result.data:
            logger.info("[Suspend] Nenhuma conta free ativa encontrada")
            return
        
        logger.info(f"[Suspend] {len(profiles_result.data)} contas free ativas para verificar")
        
        # 2. Buscar último login via auth.users (usando RPC ou admin API)
        cutoff_date = (datetime.utcnow() - timedelta(days=30)).isoformat()
        total_suspended = 0
        
        for profile in profiles_result.data:
            try:
                # Buscar last_sign_in_at via auth.admin
                user_response = supabase.auth.admin.get_user_by_id(profile["id"])
                
                if not user_response or not user_response.user:
                    continue
                
                last_sign_in = user_response.user.last_sign_in_at
                
                # Se nunca logou ou último login > 30 dias
                if last_sign_in is None or last_sign_in < cutoff_date:
                    supabase.table("profiles").update({
                        "subscription_status": "suspended",
                        "updated_at": datetime.utcnow().isoformat()
                    }).eq("id", profile["id"]).execute()
                    
                    total_suspended += 1
                    logger.debug(
                        f"[Suspend] Conta suspensa: {profile.get('email', profile['id'])} "
                        f"(último login: {last_sign_in or 'nunca'})"
                    )
                    
            except Exception as e:
                logger.error(f"[Suspend] Erro ao verificar {profile['id']}: {e}")
        
        logger.info(f"[Suspend] ✅ {total_suspended} contas suspensas de {len(profiles_result.data)} verificadas")
        
    except Exception as e:
        logger.error(f"[Suspend] Erro no job de suspensão: {e}")


async def generate_daily_messages_job():
    """
    Gera mensagens do dia para todos os usuários ativos.
    Roda diariamente às 03:01 UTC (00:01 BRT).
    Usa a lógica Python nativa (daily_message.gerar_mensagem_para_usuario).
    """
    logger.info("[MensagemDia] Iniciando geração de mensagens do dia...")
    
    try:
        from routers.daily_message import gerar_mensagem_para_usuario
        from supabase import create_client
        settings = get_settings()
        
        supabase = create_client(settings.supabase_url, settings.supabase_service_key)
        
        # Buscar todos os usuários ativos (não suspensos)
        profiles_result = supabase.table("profiles") \
            .select("id, nome, email, plano, subscription_status") \
            .neq("subscription_status", "suspended") \
            .execute()
        
        if not profiles_result.data:
            logger.info("[MensagemDia] Nenhum usuário ativo encontrado")
            return
        
        users = profiles_result.data
        logger.info(f"[MensagemDia] {len(users)} usuários ativos para gerar mensagens")
        
        total_geradas = 0
        total_cached = 0
        total_erros = 0
        
        for user in users:
            try:
                result = await gerar_mensagem_para_usuario(user["id"], "generate")
                
                if result.get("cached"):
                    total_cached += 1
                    logger.debug(f"[MensagemDia] Já existia para {user.get('email', user['id'])}")
                else:
                    total_geradas += 1
                    logger.debug(f"[MensagemDia] ✓ Gerada para {user.get('email', user['id'])}")
                
                # Rate limiting: 1s entre chamadas LLM para evitar rate limit
                await asyncio.sleep(1)
                
            except Exception as e:
                total_erros += 1
                logger.error(f"[MensagemDia] Erro para {user['id']}: {e}")
        
        logger.info(
            f"[MensagemDia] ✅ Geração completa: {total_geradas} novas, "
            f"{total_cached} cached, {total_erros} erros"
        )
        
    except Exception as e:
        logger.error(f"[MensagemDia] Erro no job de geração: {e}")


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
    
    # Job 3: Suspensão de contas free inativas (diário às 04:00 UTC)
    _scheduler.add_job(
        suspend_inactive_free_accounts_job,
        trigger=CronTrigger(hour=4, minute=0),
        id="suspend_inactive",
        name="Suspend Inactive Free Accounts",
        replace_existing=True
    )
    
    # Job 4: Geração de mensagem do dia (diário às 03:01 UTC = 00:01 BRT)
    _scheduler.add_job(
        generate_daily_messages_job,
        trigger=CronTrigger(hour=3, minute=1),
        id="generate_daily_messages",
        name="Generate Daily Messages",
        replace_existing=True
    )
    
    _scheduler.start()
    _is_running = True
    
    logger.info(
        f"Scheduler started with {settings.scheduler_interval_seconds}s interval "
        f"+ monthly centelhas + daily inactive suspension + daily messages"
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
