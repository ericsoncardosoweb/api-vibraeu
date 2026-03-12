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
# POST /disc/regenerar-insights
# ============================================

class RegenerarInsightsRequest(BaseModel):
    user_id: str
    assessment_id: str


@router.post("/disc/regenerar-insights")
async def regenerar_insights(req: RegenerarInsightsRequest, background_tasks: BackgroundTasks):
    """
    Regenera os 3 insights DISC. Limpa os insights anteriores e dispara nova geração.
    """
    if not req.user_id or not req.assessment_id:
        raise HTTPException(status_code=400, detail="user_id e assessment_id são obrigatórios")

    supabase = get_supabase_client()

    # Buscar resultado do assessment
    try:
        assessment = supabase.table("disc_assessments") \
            .select("resultado_completo, perfil_predominante, perfil_secundario, pontuacao_d, pontuacao_i, pontuacao_s, pontuacao_c") \
            .eq("id", req.assessment_id) \
            .eq("user_id", req.user_id) \
            .single() \
            .execute()

        if not assessment.data:
            raise HTTPException(status_code=404, detail="Assessment não encontrado")
    except Exception as e:
        logger.error(f"[DISC] Erro ao buscar assessment: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # Resetar insights (se existir)
    try:
        supabase.table("disc_insights").upsert({
            "user_id": req.user_id,
            "assessment_id": req.assessment_id,
            "insight_interferencia": None,
            "insight_sombra": None,
            "insight_potencia": None,
            "status": "generating",
        }, on_conflict="user_id,assessment_id").execute()
    except Exception as e:
        logger.warning(f"[DISC] Erro ao resetar insights: {e}")

    # Montar resultado para o service
    resultado = {
        "perfil_predominante": assessment.data.get("perfil_predominante"),
        "perfil_secundario": assessment.data.get("perfil_secundario"),
        "pontuacao_d": assessment.data.get("pontuacao_d", 0),
        "pontuacao_i": assessment.data.get("pontuacao_i", 0),
        "pontuacao_s": assessment.data.get("pontuacao_s", 0),
        "pontuacao_c": assessment.data.get("pontuacao_c", 0),
    }

    logger.info(f"[DISC] Regenerando insights para {req.user_id} (assessment: {req.assessment_id})")

    # Iniciar geração em background
    background_tasks.add_task(
        gerar_insights_disc,
        user_id=req.user_id,
        assessment_id=req.assessment_id,
        resultado=resultado,
    )

    return {
        "success": True,
        "message": "Regeneração iniciada. Os insights serão atualizados automaticamente.",
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
