"""
Router: Users Management (Admin)
Gerencia listagem, alteração de plano/role, bloqueio de usuários.
Usa service_role (bypassa RLS).
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from services.supabase_client import get_supabase_client

router = APIRouter()


# ============================================
# Schemas
# ============================================

class UserUpdateRequest(BaseModel):
    plano: Optional[str] = None
    admin_role: Optional[str] = None
    is_admin: Optional[bool] = None
    bloqueado: Optional[bool] = None
    centelhas: Optional[int] = None
    creditos: Optional[int] = None


class CreditAdjustRequest(BaseModel):
    quantidade: int
    motivo: str = "Ajuste manual via admin"


# ============================================
# GET /admin/users — Listar usuários
# ============================================

@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    busca: Optional[str] = None,
    plano: Optional[str] = None,
    bloqueado: Optional[bool] = None
):
    """Lista todos os perfis com paginação, busca e filtros."""
    try:
        supabase = get_supabase_client()
        
        # Query com contagem
        query = supabase.table("profiles") \
            .select(
                "id, nome, email, plano, is_admin, admin_role, "
                "creditos, centelhas, plan_credits_balance, extra_credits_balance, "
                "bloqueado, created_at, updated_at, asaas_customer_id, "
                "data_nascimento, onboarding_completed",
                count="exact"
            )
        
        # Filtros
        if plano:
            query = query.eq("plano", plano)
        if busca:
            query = query.or_(f"nome.ilike.%{busca}%,email.ilike.%{busca}%")
        if bloqueado is not None:
            query = query.eq("bloqueado", bloqueado)
        
        # Paginação
        offset = (page - 1) * limit
        query = query.range(offset, offset + limit - 1)
        
        # Ordenação
        query = query.order("created_at", desc=True)
        
        result = query.execute()
        
        return {
            "success": True,
            "data": result.data,
            "total": result.count or 0,
            "page": page,
            "limit": limit
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# GET /admin/users/{user_id} — Detalhes de um usuário
# ============================================

@router.get("/users/{user_id}")
async def get_user(user_id: str):
    """Retorna detalhes completos de um usuário + assinatura + pagamentos."""
    try:
        supabase = get_supabase_client()
        
        # Profile
        profile_res = supabase.table("profiles") \
            .select("*") \
            .eq("id", user_id) \
            .single() \
            .execute()
        
        if not profile_res.data:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        
        # Assinatura ativa
        assinatura_res = supabase.table("assinaturas") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        
        # Últimos pagamentos
        pagamentos_res = supabase.table("pagamentos") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(10) \
            .execute()
        
        return {
            "success": True,
            "data": {
                "profile": profile_res.data,
                "assinatura": assinatura_res.data[0] if assinatura_res.data else None,
                "payments": pagamentos_res.data or []
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# PUT /admin/users/{user_id} — Atualizar usuário
# ============================================

@router.put("/users/{user_id}")
async def update_user(user_id: str, data: UserUpdateRequest):
    """Atualiza campos do perfil: plano, role, bloqueio, créditos."""
    try:
        supabase = get_supabase_client()
        
        update_data = {}
        if data.plano is not None:
            update_data["plano"] = data.plano
        if data.admin_role is not None:
            update_data["admin_role"] = data.admin_role
        if data.is_admin is not None:
            update_data["is_admin"] = data.is_admin
        if data.bloqueado is not None:
            update_data["bloqueado"] = data.bloqueado
        if data.centelhas is not None:
            update_data["centelhas"] = data.centelhas
        if data.creditos is not None:
            update_data["creditos"] = data.creditos
        
        if not update_data:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
        
        result = supabase.table("profiles") \
            .update(update_data) \
            .eq("id", user_id) \
            .execute()
        
        return {"success": True, "data": result.data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# POST /admin/users/{user_id}/credits — Ajustar créditos
# ============================================

@router.post("/users/{user_id}/credits")
async def adjust_credits(user_id: str, data: CreditAdjustRequest):
    """Adiciona ou remove centelhas do usuário."""
    try:
        supabase = get_supabase_client()
        
        # Buscar saldo atual
        profile = supabase.table("profiles") \
            .select("centelhas, nome, email") \
            .eq("id", user_id) \
            .single() \
            .execute()
        
        if not profile.data:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        
        novo_saldo = max(0, (profile.data.get("centelhas") or 0) + data.quantidade)
        
        # Atualizar
        supabase.table("profiles") \
            .update({"centelhas": novo_saldo}) \
            .eq("id", user_id) \
            .execute()
        
        return {
            "success": True,
            "saldo_anterior": profile.data.get("centelhas") or 0,
            "ajuste": data.quantidade,
            "novo_saldo": novo_saldo,
            "motivo": data.motivo
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
