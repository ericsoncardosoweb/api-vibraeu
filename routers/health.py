"""
Health check endpoint.
"""

from fastapi import APIRouter
from datetime import datetime

from config import get_settings


router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Health check endpoint.
    Returns service status and basic info.
    """
    settings = get_settings()
    
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        "timestamp": datetime.utcnow().isoformat(),
        "scheduler_enabled": settings.scheduler_enabled
    }


@router.get("/health/detailed")
async def detailed_health():
    """
    Detailed health check with dependency status.
    """
    settings = get_settings()
    
    # Check Supabase connection
    supabase_status = "unknown"
    try:
        from services.supabase_client import get_supabase_client
        client = get_supabase_client()
        # Simple query to test connection
        client.table("adv_interpretation_templates").select("id").limit(1).execute()
        supabase_status = "connected"
    except Exception as e:
        supabase_status = f"error: {str(e)[:50]}"
    
    # Check LLM providers
    llm_providers = []
    if settings.groq_api_key:
        llm_providers.append("groq")
    if settings.openai_api_key:
        llm_providers.append("openai")
    if settings.gemini_api_key:
        llm_providers.append("gemini")
    
    return {
        "status": "healthy" if supabase_status == "connected" else "degraded",
        "service": settings.app_name,
        "version": settings.app_version,
        "timestamp": datetime.utcnow().isoformat(),
        "dependencies": {
            "supabase": supabase_status,
            "llm_providers": llm_providers
        },
        "config": {
            "scheduler_enabled": settings.scheduler_enabled,
            "scheduler_interval": settings.scheduler_interval_seconds,
            "default_provider": settings.default_provider,
            "fallback_provider": settings.fallback_provider
        }
    }
