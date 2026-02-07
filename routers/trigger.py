"""
Trigger endpoint - triggers interpretation generation for events.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from loguru import logger

from services.interpretation_service import InterpretationService


router = APIRouter()


class TriggerRequest(BaseModel):
    """Request model for triggering interpretations."""
    event: str
    user_id: str
    context: Optional[Dict[str, Any]] = None
    force_immediate: bool = False


class TriggerResponse(BaseModel):
    """Response model for trigger endpoint."""
    success: bool
    message: str
    queued_items: int = 0
    queue_ids: List[str] = []


@router.post("", response_model=TriggerResponse)
async def trigger_interpretation(request: TriggerRequest):
    """
    Trigger interpretation generation for an event.
    
    Events:
    - ACCOUNT_CREATED: When user creates account
    - MAC_GENERATED: When astral map is generated
    - MAC_UPDATED: When astral map is updated
    - TEST_COMPLETED: When user completes a test
    - SUBSCRIPTION_UPGRADED: When user upgrades plan
    - MANUAL_TRIGGER: Manual admin trigger
    
    Args:
        event: The trigger event name
        user_id: UUID of the user
        context: Optional additional context data
        force_immediate: Skip delay and process immediately
        
    Returns:
        TriggerResponse with queued items info
    """
    logger.info(f"Trigger received: {request.event} for user {request.user_id}")
    
    try:
        service = InterpretationService()
        result = await service.trigger_by_event(
            event=request.event,
            user_id=request.user_id,
            context=request.context,
            force_immediate=request.force_immediate
        )
        
        return TriggerResponse(
            success=True,
            message=f"Queued {result['queued_items']} interpretation(s)",
            queued_items=result["queued_items"],
            queue_ids=result["queue_ids"]
        )
        
    except Exception as e:
        logger.error(f"Trigger error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger interpretation: {str(e)}"
        )


@router.post("/batch")
async def trigger_batch(requests: List[TriggerRequest]):
    """
    Trigger multiple interpretations in batch.
    
    Useful for bulk operations like initial setup or migration.
    """
    results = []
    errors = []
    
    service = InterpretationService()
    
    for req in requests:
        try:
            result = await service.trigger_by_event(
                event=req.event,
                user_id=req.user_id,
                context=req.context,
                force_immediate=req.force_immediate
            )
            results.append({
                "user_id": req.user_id,
                "event": req.event,
                "queued": result["queued_items"]
            })
        except Exception as e:
            errors.append({
                "user_id": req.user_id,
                "event": req.event,
                "error": str(e)
            })
    
    return {
        "success": len(errors) == 0,
        "processed": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors
    }
