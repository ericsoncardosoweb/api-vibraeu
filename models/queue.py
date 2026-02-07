"""
Pydantic models for execution queue.
"""

from pydantic import BaseModel, Field
from typing import Optional, Any, Dict, List
from datetime import datetime
from enum import Enum
import uuid


class QueueStatus(str, Enum):
    """Status of a queue item."""
    PENDING = "pending"
    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionQueueItem(BaseModel):
    """Full execution queue item model."""
    id: uuid.UUID
    user_id: uuid.UUID
    template_id: uuid.UUID
    scheduled_for: datetime
    status: QueueStatus = QueueStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    context_data: Dict[str, Any] = Field(default_factory=dict)
    result_content: Optional[str] = None
    result_metadata: Optional[Dict[str, Any]] = None
    error_log: Optional[str] = None
    processing_log: List[Dict[str, Any]] = Field(default_factory=list)
    processing_started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class QueueItemCreate(BaseModel):
    """Model for creating a queue item."""
    user_id: uuid.UUID
    template_id: uuid.UUID
    scheduled_for: Optional[datetime] = None
    context_data: Optional[Dict[str, Any]] = None


class TriggerRequest(BaseModel):
    """Request model for triggering interpretation."""
    event: str
    user_id: str
    context: Optional[Dict[str, Any]] = None
    force_immediate: bool = False


class TriggerResponse(BaseModel):
    """Response model for trigger endpoint."""
    success: bool
    message: str
    queued_items: int = 0
    queue_ids: List[str] = Field(default_factory=list)


class ProcessRequest(BaseModel):
    """Request for force processing."""
    queue_id: Optional[str] = None
    user_id: Optional[str] = None
    template_key: Optional[str] = None


class ProcessResponse(BaseModel):
    """Response from processing."""
    success: bool
    message: str
    processed_count: int = 0
    results: List[Dict[str, Any]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
