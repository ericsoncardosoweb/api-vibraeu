"""
Admin router for interpretation management.
Only accessible to users with master role.
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from loguru import logger

from services.supabase_client import SupabaseService
from models.template import InterpretationTemplate, TemplateCreate, TemplateUpdate


router = APIRouter()


# Dependency to check master role (simplified - enhance with real auth)
async def verify_master_role():
    """Verify user has master role. Implement proper auth check."""
    # TODO: Implement proper JWT validation and role check
    # For now, this is a placeholder
    return True


@router.get("/templates", response_model=List[InterpretationTemplate])
async def list_templates(
    is_active: Optional[bool] = None,
    trigger_event: Optional[str] = None,
    _: bool = Depends(verify_master_role)
):
    """
    List all interpretation templates.
    
    Query params:
        - is_active: Filter by active status
        - trigger_event: Filter by trigger event
    """
    try:
        supabase = SupabaseService()
        
        query = supabase.client.table("adv_interpretation_templates").select("*")
        
        if is_active is not None:
            query = query.eq("is_active", is_active)
        
        if trigger_event:
            query = query.eq("trigger_event", trigger_event)
        
        response = query.order("priority", desc=True).execute()
        
        return response.data or []
        
    except Exception as e:
        logger.error(f"Error listing templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/templates", response_model=InterpretationTemplate)
async def create_template(
    template: TemplateCreate,
    _: bool = Depends(verify_master_role)
):
    """Create a new interpretation template."""
    try:
        supabase = SupabaseService()
        
        # Check if custom_key already exists
        existing = supabase.client.table("adv_interpretation_templates") \
            .select("id") \
            .eq("custom_key", template.custom_key) \
            .limit(1) \
            .execute()
        
        if existing.data and len(existing.data) > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Template with custom_key '{template.custom_key}' already exists"
            )
        
        # Insert new template
        response = supabase.client.table("adv_interpretation_templates") \
            .insert(template.dict()) \
            .execute()
        
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to create template")
        
        logger.info(f"Template created: {template.custom_key}")
        return response.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/templates/{template_id}", response_model=InterpretationTemplate)
async def update_template(
    template_id: str,
    template: TemplateUpdate,
    _: bool = Depends(verify_master_role)
):
    """Update an existing template."""
    try:
        supabase = SupabaseService()
        
        # Check if template exists
        existing = supabase.client.table("adv_interpretation_templates") \
            .select("id") \
            .eq("id", template_id) \
            .limit(1) \
            .execute()
        
        if not existing.data or len(existing.data) == 0:
            raise HTTPException(status_code=404, detail="Template not found")
        
        # Update template
        update_data = template.dict(exclude_unset=True)
        
        response = supabase.client.table("adv_interpretation_templates") \
            .update(update_data) \
            .eq("id", template_id) \
            .execute()
        
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to update template")
        
        logger.info(f"Template updated: {template_id}")
        return response.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: str,
    _: bool = Depends(verify_master_role)
):
    """Delete a template."""
    try:
        supabase = SupabaseService()
        
        # Check if template exists
        existing = supabase.client.table("adv_interpretation_templates") \
            .select("id, custom_key") \
            .eq("id", template_id) \
            .limit(1) \
            .execute()
        
        if not existing.data or len(existing.data) == 0:
            raise HTTPException(status_code=404, detail="Template not found")
        
        # Delete template
        supabase.client.table("adv_interpretation_templates") \
            .delete() \
            .eq("id", template_id) \
            .execute()
        
        logger.info(f"Template deleted: {existing.data[0]['custom_key']}")
        return {"success": True, "message": "Template deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue")
async def list_queue(
    status: Optional[str] = None,
    limit: int = 50,
    _: bool = Depends(verify_master_role)
):
    """
    List queue items.
    
    Query params:
        - status: Filter by status (pending, processing, completed, failed)
        - limit: Max items to return (default 50)
    """
    try:
        supabase = SupabaseService()
        
        query = supabase.client.table("adv_execution_queue") \
            .select("*, template:adv_interpretation_templates(title, custom_key)")
        
        if status:
            query = query.eq("status", status)
        
        response = query.order("created_at", desc=True).limit(limit).execute()
        
        return {
            "items": response.data or [],
            "total": len(response.data or [])
        }
        
    except Exception as e:
        logger.error(f"Error listing queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/{queue_id}/cancel")
async def cancel_queue_item(
    queue_id: str,
    _: bool = Depends(verify_master_role)
):
    """Cancel a pending queue item."""
    try:
        supabase = SupabaseService()
        
        # Check if item exists and is pending
        existing = supabase.client.table("adv_execution_queue") \
            .select("id, status") \
            .eq("id", queue_id) \
            .limit(1) \
            .execute()
        
        if not existing.data or len(existing.data) == 0:
            raise HTTPException(status_code=404, detail="Queue item not found")
        
        if existing.data[0]["status"] != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel item with status: {existing.data[0]['status']}"
            )
        
        # Update status to cancelled
        supabase.client.table("adv_execution_queue") \
            .update({"status": "cancelled"}) \
            .eq("id", queue_id) \
            .execute()
        
        logger.info(f"Queue item cancelled: {queue_id}")
        return {"success": True, "message": "Queue item cancelled"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling queue item: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/variables")
async def list_variables(
    is_active: bool = True,
    _: bool = Depends(verify_master_role)
):
    """List available variables for prompts."""
    try:
        supabase = SupabaseService()
        
        query = supabase.client.table("adv_interpretation_variables").select("*")
        
        if is_active:
            query = query.eq("is_active", True)
        
        response = query.order("sort_order").execute()
        
        return response.data or []
        
    except Exception as e:
        logger.error(f"Error listing variables: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_stats(
    _: bool = Depends(verify_master_role)
):
    """Get admin statistics."""
    try:
        supabase = SupabaseService()
        
        # Count templates
        templates_response = supabase.client.table("adv_interpretation_templates") \
            .select("id", count="exact") \
            .execute()
        
        # Count queue by status
        queue_stats = {}
        for status in ["pending", "processing", "completed", "failed"]:
            count_response = supabase.client.table("adv_execution_queue") \
                .select("id", count="exact") \
                .eq("status", status) \
                .execute()
            queue_stats[status] = count_response.count or 0
        
        return {
            "templates": {
                "total": templates_response.count or 0
            },
            "queue": queue_stats
        }
        
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# TRIGGER EVENTS
# =============================================================================

from pydantic import BaseModel
from typing import Dict, Any
from datetime import datetime

class TriggerEventRequest(BaseModel):
    event_type: str
    user_id: str
    context_data: Optional[Dict[str, Any]] = {}


@router.post("/trigger-event")
async def trigger_event(
    request: TriggerEventRequest
):
    """
    Trigger an AIMS event for a user.
    Finds matching templates and adds items to the execution queue.
    
    This endpoint is called by the frontend when events occur (MAC generated, etc).
    """
    try:
        supabase = SupabaseService()
        
        logger.info(f"AIMS Event triggered: {request.event_type} for user {request.user_id}")
        
        # ================================================================
        # DETERMINAR PERFIL DO USUÁRIO (premium/free)
        # ================================================================
        user_response = supabase.client.table("profiles") \
            .select("plano") \
            .eq("id", request.user_id) \
            .limit(1) \
            .execute()
        
        user_plan = "semente"  # Default
        if user_response.data and user_response.data[0].get("plano"):
            plan = user_response.data[0]["plano"].lower()
            if plan in ["fluxo", "expansao"]:
                user_plan = "premium"
        
        logger.info(f"User plan: {user_plan}")
        
        # Find active templates matching this trigger event
        templates_response = supabase.client.table("adv_interpretation_templates") \
            .select("*") \
            .eq("trigger_event", request.event_type) \
            .eq("is_active", True) \
            .order("priority", desc=True) \
            .execute()
        
        all_templates = templates_response.data or []
        
        # ================================================================
        # FILTRAR POR TARGET_PROFILES
        # ================================================================
        # Lógica:
        # - "active_user" + qualquer plano: executa para o usuário ativo
        # - "all": executa para todos independente do plano
        # - "premium": apenas se user_plan == "premium"
        # - "free"/"semente": apenas se user_plan não é premium
        
        templates = []
        for t in all_templates:
            target_profiles = t.get("target_profiles", ["active_user"])
            
            # "all" ou "active_user" sempre passam
            if "all" in target_profiles or "active_user" in target_profiles:
                templates.append(t)
            # Filtrar por plano (aceitar 'free' e 'semente' como equivalentes)
            elif user_plan in target_profiles:
                templates.append(t)
            elif user_plan in ["free", "semente"] and ("free" in target_profiles or "semente" in target_profiles):
                templates.append(t)
        
        logger.info(f"Templates matched: {len(templates)} of {len(all_templates)}")
        
        if not templates:
            logger.info(f"No templates matched for event: {request.event_type}, user plan: {user_plan}")
            return {
                "success": True,
                "message": "No templates matched",
                "queued_items": 0
            }
        
        # Add each matching template to the execution queue
        queued_items = []
        
        for template in templates:
            target_profiles = template.get("target_profiles", ["active_user"])
            
            # Calculate scheduled_for based on delay settings
            delay_days = template.get("release_delay_days", 0) or 0
            delay_hours = template.get("release_delay_hours", 0) or 0
            
            scheduled_for = datetime.utcnow()
            if delay_days > 0 or delay_hours > 0:
                from datetime import timedelta
                scheduled_for = scheduled_for + timedelta(days=delay_days, hours=delay_hours)
            
            # ================================================================
            # DETERMINAR USUÁRIOS ALVO BASEADO NO TARGET_PROFILES
            # ================================================================
            target_user_ids = []
            
            if "all" in target_profiles:
                # Buscar TODOS os usuários
                users_response = supabase.client.table("profiles") \
                    .select("id") \
                    .execute()
                target_user_ids = [u["id"] for u in (users_response.data or [])]
                logger.info(f"Batch ALL: {len(target_user_ids)} users")
                
            elif "all_premium" in target_profiles:
                # Buscar todos os usuários premium
                premium_plans = ["fluxo", "expansao"]
                users_response = supabase.client.table("profiles") \
                    .select("id, plano") \
                    .execute()
                target_user_ids = [
                    u["id"] for u in (users_response.data or [])
                    if u.get("plano", "").lower() in premium_plans
                ]
                logger.info(f"Batch ALL_PREMIUM: {len(target_user_ids)} users")
                
            elif "all_free" in target_profiles:
                # Buscar todos os usuários free
                premium_plans = ["fluxo", "expansao"]
                users_response = supabase.client.table("profiles") \
                    .select("id, plano") \
                    .execute()
                target_user_ids = [
                    u["id"] for u in (users_response.data or [])
                    if u.get("plano", "").lower() not in premium_plans
                ]
                logger.info(f"Batch ALL_FREE: {len(target_user_ids)} users")
                
            else:
                # Modos de trigger individual: active_user, premium, free
                # Já foi filtrado anteriormente, usar o usuário que disparou
                target_user_ids = [request.user_id]
            
            # ================================================================
            # CRIAR ITENS NA FILA PARA CADA USUÁRIO
            # ================================================================
            for uid in target_user_ids:
                queue_item = {
                    "user_id": uid,
                    "template_id": template["id"],
                    "status": "pending",
                    "scheduled_for": scheduled_for.isoformat(),
                    "context_data": {
                        **request.context_data,
                        "trigger_event": request.event_type,
                        "template_key": template.get("custom_key"),
                        "batch_mode": "all" in target_profiles or "all_premium" in target_profiles or "all_free" in target_profiles
                    }
                }
                
                # Insert into queue
                insert_response = supabase.client.table("adv_execution_queue") \
                    .insert(queue_item) \
                    .execute()
                
                if insert_response.data:
                    queued_items.append({
                        "queue_id": insert_response.data[0]["id"],
                        "user_id": uid,
                        "template_key": template.get("custom_key"),
                        "scheduled_for": scheduled_for.isoformat()
                    })
            
            logger.info(f"Queued {len(target_user_ids)} item(s) for template: {template.get('custom_key')}")
        
        return {
            "success": True,
            "message": f"Queued {len(queued_items)} interpretation(s)",
            "queued_items": len(queued_items),
            "items": queued_items[:10]  # Limitar retorno para não sobrecarregar
        }
        
    except Exception as e:
        logger.error(f"Error triggering event: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process-queue")
async def process_queue(
    limit: int = 10,
    _: bool = Depends(verify_master_role)
):
    """
    Manually trigger queue processing.
    In production, this would be called by a scheduler/cron job.
    """
    try:
        from services.aims_engine import get_engine
        
        engine = get_engine()
        result = await engine.process_queue(limit=limit)
        
        return {
            "success": True,
            "result": result
        }
        
    except Exception as e:
        logger.error(f"Error processing queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue")
async def list_queue(
    status: Optional[str] = None,
    limit: int = 50,
    _: bool = Depends(verify_master_role)
):
    """List items in the execution queue."""
    try:
        supabase = SupabaseService()
        
        query = supabase.client.table("adv_execution_queue") \
            .select("*, template:adv_interpretation_templates(title, custom_key)")
        
        if status:
            query = query.eq("status", status)
        
        response = query.order("created_at", desc=True).limit(limit).execute()
        
        return response.data or []
        
    except Exception as e:
        logger.error(f"Error listing queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/interpretations")
async def list_interpretations(
    user_id: Optional[str] = None,
    module_relation: Optional[str] = None,
    limit: int = 50,
    _: bool = Depends(verify_master_role)
):
    """List generated interpretations (admin view)."""
    try:
        supabase = SupabaseService()
        
        query = supabase.client.table("adv_interpretations") \
            .select("*, template:adv_interpretation_templates(title, custom_key), user:profiles(name, email)")
        
        if user_id:
            query = query.eq("user_id", user_id)
        
        if module_relation:
            query = query.eq("module_relation", module_relation)
        
        response = query.order("created_at", desc=True).limit(limit).execute()
        
        return response.data or []
        
    except Exception as e:
        logger.error(f"Error listing interpretations: {e}")
        raise HTTPException(status_code=500, detail=str(e))

