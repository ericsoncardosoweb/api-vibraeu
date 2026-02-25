"""
DISC Router — Endpoints para geração de insights DISC.
Endpoints:
    POST /disc/gerar-insights — Gera 3 insights (Interferência, Sombra, Potência) em background
    GET  /disc/insights/{user_id}/{assessment_id} — Busca insights de um assessment
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any
from loguru import logger

from services.disc_service import gerar_insights_disc
from services.supabase_client import get_supabase_client

router = APIRouter()


# ============================================
# Models
# ============================================

class GerarInsightsDISCRequest(BaseModel):
    user_id: str
    assessment_id: str
    resultado: Dict[str, Any]


# ============================================
# POST /disc/gerar-insights
# ============================================

@router.post("/disc/gerar-insights")
async def gerar_insights(req: GerarInsightsDISCRequest, background_tasks: BackgroundTasks):
    """
    Inicia a geração dos 3 insights DISC (Interferência, Sombra, Potência).
    A geração roda em background. O frontend faz polling via GET.
    """
    if not req.user_id or not req.assessment_id:
        raise HTTPException(status_code=400, detail="user_id e assessment_id são obrigatórios")

    if not req.resultado:
        raise HTTPException(status_code=400, detail="Dados do resultado DISC são obrigatórios")

    logger.info(f"[DISC] Recebido pedido de insights para {req.user_id} (assessment: {req.assessment_id})")

    # Iniciar geração em background para não bloquear o request
    background_tasks.add_task(
        gerar_insights_disc,
        user_id=req.user_id,
        assessment_id=req.assessment_id,
        resultado=req.resultado,
    )

    return {
        "success": True,
        "message": "Geração iniciada. Os insights serão salvos automaticamente.",
        "status": "generating",
    }


# ============================================
# GET /disc/insights/{user_id}/{assessment_id}
# ============================================

@router.get("/disc/insights/{user_id}/{assessment_id}")
async def get_insights(user_id: str, assessment_id: str):
    """Busca insights de um assessment DISC."""
    supabase = get_supabase_client()

    try:
        response = supabase.table("disc_insights") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("assessment_id", assessment_id) \
            .maybe_single() \
            .execute()

        data = response.data

        return {
            "success": True,
            "data": data,
        }
    except Exception as e:
        logger.error(f"[DISC] Erro ao buscar insights: {e}")
        raise HTTPException(status_code=500, detail=str(e))
