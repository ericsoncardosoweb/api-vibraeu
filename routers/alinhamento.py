"""
Alinhamento Router — Endpoints para geração de insights de alinhamento.
Substitui o webhook n8n (vibraeu-alinhamento).
Endpoints:
    POST /alinhamento/gerar-insights — Gera todos os insights (Espelho, Fluxo, Caminho)
    GET  /alinhamento/insight/{user_id} — Busca insight do mês atual
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any
from loguru import logger

from services.alinhamento_service import gerar_insights_alinhamento
from services.supabase_client import get_supabase_client
from services.monthly_reports_service import get_mes_referencia

router = APIRouter()


# ============================================
# Models
# ============================================

class GerarInsightsRequest(BaseModel):
    user_id: str
    checkin_id: str
    checkin: Dict[str, Any]
    perfil: Dict[str, Any]
    mes_referencia: Optional[str] = None


# ============================================
# POST /alinhamento/gerar-insights
# ============================================

@router.post("/alinhamento/gerar-insights")
async def gerar_insights(req: GerarInsightsRequest, background_tasks: BackgroundTasks):
    """
    Inicia a geração dos 3 insights (Espelho, Fluxo, Caminho).
    A geração roda em background. O frontend faz polling via GET.
    """
    if not req.user_id or not req.checkin_id:
        raise HTTPException(status_code=400, detail="user_id e checkin_id são obrigatórios")

    if not req.checkin:
        raise HTTPException(status_code=400, detail="Dados do check-in são obrigatórios")

    logger.info(f"[Alinhamento] Recebido pedido de insights para {req.user_id}")

    # Iniciar geração em background para não bloquear o request
    background_tasks.add_task(
        gerar_insights_alinhamento,
        user_id=req.user_id,
        checkin_id=req.checkin_id,
        checkin_data=req.checkin,
        perfil=req.perfil,
        mes_referencia=req.mes_referencia,
    )

    return {
        "success": True,
        "message": "Geração iniciada. Os insights serão salvos automaticamente.",
        "status": "generating",
    }


# ============================================
# GET /alinhamento/insight/{user_id}
# ============================================

@router.get("/alinhamento/insight/{user_id}")
async def get_insight(user_id: str, mes: Optional[str] = None):
    """Busca insight do mês atual ou especificado."""
    mes_ref = get_mes_referencia(mes)
    supabase = get_supabase_client()

    try:
        response = supabase.table("alinhamento_insights") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("mes_referencia", mes_ref) \
            .maybe_single() \
            .execute()

        data = response.data

        return {
            "success": True,
            "data": data,
            "mes_referencia": mes_ref,
        }
    except Exception as e:
        logger.error(f"[Alinhamento] Erro ao buscar insight: {e}")
        raise HTTPException(status_code=500, detail=str(e))
