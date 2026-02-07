"""
Plans & Modules router — Dynamic plan configuration via Supabase.
Public endpoints for apps to read config. Admin endpoints for CRUD.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from loguru import logger

from services.supabase_client import get_supabase_client


router = APIRouter()


# =============================================================================
# Models
# =============================================================================

class PlanUpdate(BaseModel):
    nome: Optional[str] = None
    preco_mensal: Optional[float] = None
    preco_anual: Optional[float] = None
    cor: Optional[str] = None
    cor_gradient: Optional[str] = None
    icone: Optional[str] = None
    centelhas_mensais: Optional[int] = None
    badge: Optional[str] = None
    descricao: Optional[str] = None
    features: Optional[list] = None
    ordem: Optional[int] = None
    ativo: Optional[bool] = None


class ModuloUpdate(BaseModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    categoria: Optional[str] = None
    planos_permitidos: Optional[List[str]] = None
    custo_centelhas: Optional[int] = None
    ordem: Optional[int] = None
    ativo: Optional[bool] = None


class ModuloCreate(BaseModel):
    codigo: str
    nome: str
    descricao: str = ""
    categoria: str
    planos_permitidos: List[str] = []
    custo_centelhas: int = 0
    ordem: int = 0


class PacoteUpdate(BaseModel):
    quantidade: Optional[int] = None
    preco: Optional[float] = None
    bonus: Optional[int] = None
    descricao: Optional[str] = None
    melhor_valor: Optional[bool] = None
    ordem: Optional[int] = None
    ativo: Optional[bool] = None


# =============================================================================
# PUBLIC ENDPOINTS — For apps to consume
# =============================================================================

@router.get("/plans/config")
async def get_plans_config():
    """
    Returns the full plans configuration: plans, modules/permissions, and spark packages.
    This is the single source of truth for all apps (app, admin, checkout).
    No authentication required — public data.
    """
    try:
        supabase = get_supabase_client()

        # Fetch all 3 tables in parallel-ish (Supabase client is sync)
        planos_res = supabase.table("planos_config") \
            .select("*") \
            .eq("ativo", True) \
            .order("ordem") \
            .execute()

        modulos_res = supabase.table("modulos_permissoes") \
            .select("*") \
            .eq("ativo", True) \
            .order("ordem") \
            .execute()

        pacotes_res = supabase.table("pacotes_centelhas") \
            .select("*") \
            .eq("ativo", True) \
            .order("ordem") \
            .execute()

        # Build permissions map (same format as planos.js PERMISSOES_MODULOS)
        permissoes = {}
        custos = {}
        for mod in (modulos_res.data or []):
            permissoes[mod["codigo"]] = mod.get("planos_permitidos", [])
            if mod.get("custo_centelhas", 0) > 0:
                custos[mod["codigo"]] = {
                    "custo": mod["custo_centelhas"],
                    "nome": mod["nome"],
                    "descricao": mod.get("descricao", "")
                }

        # Build plans array (same format as planos.js PLANOS)
        planos = {}
        planos_array = []
        for p in (planos_res.data or []):
            plan_obj = {
                "id": p["id"],
                "nome": p["nome"],
                "codigo": p["id"],
                "preco": float(p["preco_mensal"]),
                "precoAnual": float(p["preco_anual"]) if p.get("preco_anual") else None,
                "periodo": "/mês" if float(p["preco_mensal"]) > 0 else "",
                "cor": p.get("cor", "#6B7280"),
                "corGradient": p.get("cor_gradient"),
                "icone": p.get("icone", "fa-star"),
                "centelhasMensais": p.get("centelhas_mensais", 0),
                "badge": p.get("badge"),
                "descricao": p.get("descricao", ""),
                "features": p.get("features", [])
            }
            planos[p["id"]] = plan_obj
            planos_array.append(plan_obj)

        # Build packages array
        pacotes = []
        for pkg in (pacotes_res.data or []):
            pacotes.append({
                "id": pkg["id"],
                "quantidade": pkg["quantidade"],
                "preco": float(pkg["preco"]),
                "bonus": pkg.get("bonus", 0),
                "descricao": pkg.get("descricao", ""),
                "melhorValor": pkg.get("melhor_valor", False)
            })

        return {
            "planos": planos,
            "planosArray": planos_array,
            "permissoes": permissoes,
            "custoCentelhas": custos,
            "pacotesCentelhas": pacotes,
            # Raw data for admin
            "modulos": modulos_res.data or []
        }

    except Exception as e:
        logger.error(f"❌ Error fetching plans config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ADMIN ENDPOINTS — Plan CRUD
# =============================================================================

@router.put("/plans/{plan_id}")
async def update_plan(plan_id: str, data: PlanUpdate):
    """Update a plan configuration."""
    try:
        supabase = get_supabase_client()

        update_data = data.model_dump(exclude_none=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        result = supabase.table("planos_config") \
            .update(update_data) \
            .eq("id", plan_id) \
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail=f"Plano '{plan_id}' não encontrado")

        logger.info(f"✅ Plan '{plan_id}' updated: {list(update_data.keys())}")
        return {"success": True, "data": result.data[0]}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating plan '{plan_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ADMIN ENDPOINTS — Module CRUD
# =============================================================================

@router.post("/plans/modulos")
async def create_modulo(data: ModuloCreate):
    """Create a new module."""
    try:
        supabase = get_supabase_client()

        insert_data = data.model_dump()
        result = supabase.table("modulos_permissoes") \
            .insert(insert_data) \
            .execute()

        logger.info(f"✅ Module '{data.codigo}' created")
        return {"success": True, "data": result.data[0]}

    except Exception as e:
        logger.error(f"❌ Error creating module: {e}")
        if "duplicate key" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"Módulo '{data.codigo}' já existe")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/plans/modulos/{codigo}")
async def update_modulo(codigo: str, data: ModuloUpdate):
    """Update a module's permissions or config."""
    try:
        supabase = get_supabase_client()

        update_data = data.model_dump(exclude_none=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        result = supabase.table("modulos_permissoes") \
            .update(update_data) \
            .eq("codigo", codigo) \
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail=f"Módulo '{codigo}' não encontrado")

        logger.info(f"✅ Module '{codigo}' updated: {list(update_data.keys())}")
        return {"success": True, "data": result.data[0]}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating module '{codigo}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/plans/modulos/{codigo}")
async def delete_modulo(codigo: str):
    """Delete a module."""
    try:
        supabase = get_supabase_client()

        result = supabase.table("modulos_permissoes") \
            .delete() \
            .eq("codigo", codigo) \
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail=f"Módulo '{codigo}' não encontrado")

        logger.info(f"🗑️ Module '{codigo}' deleted")
        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting module '{codigo}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ADMIN ENDPOINTS — Centelhas Package CRUD
# =============================================================================

@router.put("/plans/pacotes/{pacote_id}")
async def update_pacote(pacote_id: str, data: PacoteUpdate):
    """Update a spark package."""
    try:
        supabase = get_supabase_client()

        update_data = data.model_dump(exclude_none=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        result = supabase.table("pacotes_centelhas") \
            .update(update_data) \
            .eq("id", pacote_id) \
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail=f"Pacote '{pacote_id}' não encontrado")

        logger.info(f"✅ Package '{pacote_id}' updated: {list(update_data.keys())}")
        return {"success": True, "data": result.data[0]}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating package '{pacote_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))
