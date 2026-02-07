"""
Health check endpoint with performance metrics.
"""

from fastapi import APIRouter, Request
from datetime import datetime
import time

from config import get_settings


router = APIRouter()


@router.get("/health")
async def health_check(request: Request):
    """
    Health check endpoint.
    Returns service status and basic info.
    """
    settings = get_settings()
    
    # Uptime
    uptime_seconds = 0
    if hasattr(request.app.state, 'start_time'):
        uptime_seconds = int(time.time() - request.app.state.start_time)
    
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        "timestamp": datetime.utcnow().isoformat(),
        "uptime": f"{hours}h {minutes}m {secs}s",
        "scheduler_enabled": settings.scheduler_enabled
    }


@router.get("/health/detailed")
async def detailed_health(request: Request):
    """
    Detailed health check with dependency status and performance metrics.
    """
    settings = get_settings()
    
    # Uptime
    uptime_seconds = 0
    if hasattr(request.app.state, 'start_time'):
        uptime_seconds = int(time.time() - request.app.state.start_time)
    
    # Check Supabase connection
    supabase_status = "unknown"
    try:
        from services.supabase_client import get_supabase_client
        client = get_supabase_client()
        client.table("adv_interpretation_templates").select("id").limit(1).execute()
        supabase_status = "connected"
    except Exception as e:
        supabase_status = f"error: {str(e)[:50]}"
    
    # Check LLM providers + stats
    llm_stats = {}
    try:
        from services.llm_gateway import LLMGateway
        gateway = LLMGateway.get_instance()
        llm_stats = gateway.stats
    except Exception:
        llm_stats = {"providers": [], "error": "not initialized"}
    
    # Cache stats
    cache_stats = {}
    try:
        from services.cache import db_cache, response_cache
        cache_stats = {
            "db_cache": db_cache.stats,
            "response_cache": response_cache.stats
        }
    except Exception:
        cache_stats = {"error": "not available"}
    
    return {
        "status": "healthy" if supabase_status == "connected" else "degraded",
        "service": settings.app_name,
        "version": settings.app_version,
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_seconds": uptime_seconds,
        "dependencies": {
            "supabase": supabase_status,
            "llm": llm_stats
        },
        "performance": {
            "gzip": True,
            "http_pool": True,
            "cache": cache_stats
        },
        "config": {
            "scheduler_enabled": settings.scheduler_enabled,
            "scheduler_interval": settings.scheduler_interval_seconds,
            "default_provider": settings.default_provider,
            "fallback_provider": settings.fallback_provider
        }
    }
