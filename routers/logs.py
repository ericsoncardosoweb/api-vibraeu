"""
Router de logs de erro — Recebe erros do frontend e armazena no Supabase.
Endpoints:
  - POST /logs/error      → Registrar erro(s)
  - GET  /logs/errors     → Listar erros (com filtros)
  - PATCH /logs/errors/{id}/resolve → Marcar como resolvido
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from loguru import logger
from datetime import datetime
import uuid

router = APIRouter(prefix="/logs", tags=["logs"])


# --- MODELOS ---

class ErrorLogEntry(BaseModel):
    service: str
    endpoint: Optional[str] = None
    error_message: str
    error_stack: Optional[str] = None
    status_code: Optional[int] = None
    request_body: Optional[dict] = None
    user_id: Optional[str] = None
    metadata: Optional[dict] = None


class ErrorLogBatch(BaseModel):
    errors: List[ErrorLogEntry]


# --- ROTAS ---

@router.post("/error")
async def log_errors(batch: ErrorLogBatch):
    """
    Registra um ou mais erros no banco.
    Chamado automaticamente pelo apiClient.js do frontend.
    """
    try:
        from services.supabase_client import get_supabase_client
        supabase = get_supabase_client()
        
        if not supabase:
            # Se Supabase não disponível, apenas logar localmente
            for err in batch.errors:
                logger.error(f"[ErrorLog] {err.service} {err.endpoint}: {err.error_message}")
            return {"success": True, "logged": len(batch.errors), "storage": "local"}
        
        records = []
        for err in batch.errors:
            records.append({
                "id": str(uuid.uuid4()),
                "service": err.service,
                "endpoint": err.endpoint,
                "error_message": err.error_message[:1000],  # Limitar tamanho
                "error_stack": err.error_stack[:2000] if err.error_stack else None,
                "status_code": err.status_code,
                "request_body": err.request_body,
                "user_id": err.user_id,
                "metadata": err.metadata,
                "resolved": False
            })
        
        result = supabase.table("api_error_logs").insert(records).execute()
        
        logger.info(f"[ErrorLog] {len(records)} erro(s) registrado(s)")
        return {"success": True, "logged": len(records)}
        
    except Exception as e:
        # Não propagar erro — o sistema de log não pode derrubar a aplicação
        logger.error(f"[ErrorLog] Falha ao salvar logs: {e}")
        return {"success": False, "error": str(e)}


@router.get("/errors")
async def list_errors(
    service: Optional[str] = Query(None, description="Filtrar por serviço"),
    resolved: Optional[bool] = Query(None, description="Filtrar por status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """
    Lista erros com filtros opcionais.
    Usado pela página admin e pela consulta interna de debug.
    """
    try:
        from services.supabase_client import get_supabase_client
        supabase = get_supabase_client()
        
        if not supabase:
            return {"success": False, "error": "Supabase não configurado"}
        
        query = supabase.table("api_error_logs") \
            .select("*") \
            .order("created_at", desc=True) \
            .range(offset, offset + limit - 1)
        
        if service:
            query = query.eq("service", service)
        if resolved is not None:
            query = query.eq("resolved", resolved)
        
        result = query.execute()
        
        # Contar total (para paginação)
        count_query = supabase.table("api_error_logs").select("id", count="exact")
        if service:
            count_query = count_query.eq("service", service)
        if resolved is not None:
            count_query = count_query.eq("resolved", resolved)
        count_result = count_query.execute()
        
        return {
            "success": True,
            "data": result.data,
            "total": count_result.count if hasattr(count_result, 'count') else len(result.data),
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        logger.error(f"[ErrorLog] Falha ao listar logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/errors/{error_id}/resolve")
async def resolve_error(error_id: str):
    """Marcar um erro como resolvido."""
    try:
        from services.supabase_client import get_supabase_client
        supabase = get_supabase_client()
        
        if not supabase:
            raise HTTPException(status_code=503, detail="Supabase não configurado")
        
        result = supabase.table("api_error_logs") \
            .update({
                "resolved": True,
                "resolved_at": datetime.utcnow().isoformat()
            }) \
            .eq("id", error_id) \
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Erro não encontrado")
        
        return {"success": True, "data": result.data[0]}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ErrorLog] Falha ao resolver erro: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/errors/resolve-all")
async def resolve_all_errors(service: Optional[str] = Query(None)):
    """Marcar todos os erros (opcionalmente de um serviço) como resolvidos."""
    try:
        from services.supabase_client import get_supabase_client
        supabase = get_supabase_client()
        
        if not supabase:
            raise HTTPException(status_code=503, detail="Supabase não configurado")
        
        query = supabase.table("api_error_logs") \
            .update({
                "resolved": True,
                "resolved_at": datetime.utcnow().isoformat()
            }) \
            .eq("resolved", False)
        
        if service:
            query = query.eq("service", service)
        
        result = query.execute()
        
        count = len(result.data) if result.data else 0
        return {"success": True, "resolved_count": count}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ErrorLog] Falha ao resolver erros: {e}")
        raise HTTPException(status_code=500, detail=str(e))
