"""
Monthly Reports Router — Endpoints para relatórios mensais.
Endpoints:
    POST /reports/generate/{report_type} — Gerar relatório mensal
    GET  /reports/{user_id}/{report_type}  — Buscar relatório do mês
    GET  /reports/{user_id}/history        — Histórico de relatórios
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from loguru import logger

from services.supabase_client import get_supabase_client
from services.monthly_reports_service import (
    gerar_relatorio_diario,
    gerar_relatorio_metas,
    get_mes_referencia
)

router = APIRouter()


# ============================================
# Models
# ============================================

class GenerateReportRequest(BaseModel):
    user_id: str
    mes_referencia: Optional[str] = None  # Formato YYYY-MM, default = mês atual


# ============================================
# POST /reports/generate/{report_type}
# ============================================

@router.post("/reports/generate/{report_type}")
async def generate_report(report_type: str, req: GenerateReportRequest):
    """Gera relatório mensal para um tipo específico."""
    
    if report_type not in ("diario", "metas"):
        raise HTTPException(status_code=400, detail="Tipo inválido. Use 'diario' ou 'metas'.")
    
    if not req.user_id:
        raise HTTPException(status_code=400, detail="user_id é obrigatório")
    
    try:
        if report_type == "diario":
            result = await gerar_relatorio_diario(req.user_id, req.mes_referencia)
        else:
            result = await gerar_relatorio_metas(req.user_id, req.mes_referencia)
        
        if not result.get("success"):
            raise HTTPException(
                status_code=422,
                detail=result.get("error", "Erro ao gerar relatório")
            )
        
        return {
            "success": True,
            "report_type": report_type,
            "data": result.get("data"),
            "already_exists": result.get("already_exists", False)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MonthlyReports] Erro no endpoint generate: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# GET /reports/{user_id}/{report_type}
# ============================================

@router.get("/reports/{user_id}/{report_type}")
async def get_report(user_id: str, report_type: str, mes: Optional[str] = None):
    """Busca relatório do mês atual ou especificado."""
    
    if report_type not in ("diario", "metas"):
        raise HTTPException(status_code=400, detail="Tipo inválido. Use 'diario' ou 'metas'.")
    
    mes_ref = get_mes_referencia(mes)
    supabase = get_supabase_client()
    
    try:
        response = supabase.table("monthly_reports") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("report_type", report_type) \
            .eq("mes_referencia", mes_ref) \
            .execute()
        
        data = response.data[0] if response.data else None
        
        return {
            "success": True,
            "data": data,
            "mes_referencia": mes_ref
        }
    except Exception as e:
        logger.error(f"[MonthlyReports] Erro ao buscar relatório: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# GET /reports/{user_id}/history
# ============================================

@router.get("/reports/{user_id}/history")
async def get_report_history(user_id: str, report_type: Optional[str] = None, limit: int = 6):
    """Busca histórico de relatórios mensais."""
    
    supabase = get_supabase_client()
    
    try:
        query = supabase.table("monthly_reports") \
            .select("id, user_id, report_type, mes_referencia, status, created_at, updated_at") \
            .eq("user_id", user_id) \
            .order("mes_referencia", desc=True) \
            .limit(limit)
        
        if report_type and report_type in ("diario", "metas"):
            query = query.eq("report_type", report_type)
        
        response = query.execute()
        
        return {
            "success": True,
            "data": response.data or [],
            "total": len(response.data or [])
        }
    except Exception as e:
        logger.error(f"[MonthlyReports] Erro ao buscar histórico: {e}")
        raise HTTPException(status_code=500, detail=str(e))
