"""
Process endpoint - force processing of interpretations.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from loguru import logger

from services.interpretation_service import InterpretationService


router = APIRouter()


class ProcessNowRequest(BaseModel):
    """Request for force processing."""
    user_id: str
    template_key: str


class ProcessPendingRequest(BaseModel):
    """Request for processing pending items."""
    limit: int = 10


class ProcessResponse(BaseModel):
    """Response from processing."""
    success: bool
    message: str
    processed: int = 0
    failed: int = 0
    results: List[Dict[str, Any]] = []
    errors: List[str] = []


@router.post("/now", response_model=ProcessResponse)
async def process_now(request: ProcessNowRequest):
    """
    Force immediate processing of a specific interpretation.
    
    Bypasses the queue and scheduling, processing immediately.
    Useful for admin testing or priority requests.
    
    Args:
        user_id: The user UUID
        template_key: The template custom_key (e.g., 'mac-sol')
        
    Returns:
        ProcessResponse with result
    """
    logger.info(f"Force process: {request.template_key} for {request.user_id}")
    
    try:
        service = InterpretationService()
        result = await service.force_process(
            user_id=request.user_id,
            template_key=request.template_key
        )
        
        if result["success"]:
            return ProcessResponse(
                success=True,
                message="Processing completed successfully",
                processed=1,
                results=[result]
            )
        else:
            return ProcessResponse(
                success=False,
                message=result.get("error", "Processing failed"),
                failed=1,
                errors=[result.get("error", "Unknown error")]
            )
            
    except Exception as e:
        logger.error(f"Process error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process interpretation: {str(e)}"
        )


@router.post("/pending", response_model=ProcessResponse)
async def process_pending(request: ProcessPendingRequest = ProcessPendingRequest()):
    """
    Process pending queue items.
    
    Fetches items from the queue that are due for processing
    and processes them in order.
    
    Args:
        limit: Maximum number of items to process (default 10)
        
    Returns:
        ProcessResponse with results summary
    """
    logger.info(f"Processing pending items, limit: {request.limit}")
    
    try:
        service = InterpretationService()
        result = await service.process_pending(limit=request.limit)
        
        return ProcessResponse(
            success=result["success"],
            message=f"Processed {result['processed']} items",
            processed=result["processed"],
            failed=result.get("failed", 0),
            results=result.get("results", []),
            errors=result.get("errors", [])
        )
        
    except Exception as e:
        logger.error(f"Process pending error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process pending items: {str(e)}"
        )


@router.get("/queue/status")
async def queue_status():
    """
    Get current queue status.
    
    Returns counts of items by status.
    """
    try:
        from services.supabase_client import SupabaseService
        db = SupabaseService()
        
        # Get counts by status
        pending = await db.get_pending_queue_items(limit=1000)
        
        return {
            "pending": len(pending),
            "message": f"{len(pending)} items pending"
        }
        
    except Exception as e:
        logger.error(f"Queue status error: {e}")
        return {"error": str(e)}
