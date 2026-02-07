"""
Pydantic models for interpretation templates.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from enum import Enum
import uuid


class TriggerEvent(str, Enum):
    """Events that can trigger interpretation generation."""
    ACCOUNT_CREATED = "ACCOUNT_CREATED"
    MAC_GENERATED = "MAC_GENERATED"
    MAC_UPDATED = "MAC_UPDATED"
    TEST_COMPLETED = "TEST_COMPLETED"
    SUBSCRIPTION_UPGRADED = "SUBSCRIPTION_UPGRADED"
    MANUAL_TRIGGER = "MANUAL_TRIGGER"
    SCHEDULED = "SCHEDULED"


class LLMConfig(BaseModel):
    """LLM configuration for a template."""
    provider: str = "groq"
    model: str = "llama-3.3-70b-versatile"
    fallback_provider: Optional[str] = "openai"
    fallback_model: Optional[str] = "gpt-4.1-mini"
    temperature: float = 0.7
    max_tokens: int = 2000


class InterpretationTemplate(BaseModel):
    """Full interpretation template model."""
    id: uuid.UUID
    title: str
    description: Optional[str] = None
    module_relation: str = "mac"
    custom_key: str
    prompt_content: str
    system_prompt: Optional[str] = None
    release_delay_days: int = 0
    release_delay_hours: int = 0
    trigger_event: TriggerEvent = TriggerEvent.MAC_GENERATED
    spark_cost: int = 0
    target_profiles: List[str] = ["all"]
    llm_config: LLMConfig = Field(default_factory=LLMConfig)
    is_active: bool = True
    priority: int = 0
    version: int = 1
    created_at: datetime
    updated_at: datetime
    created_by: Optional[uuid.UUID] = None

    class Config:
        from_attributes = True


class TemplateCreate(BaseModel):
    """Model for creating a new template."""
    title: str
    description: Optional[str] = None
    module_relation: str = "mac"
    custom_key: str
    prompt_content: str
    system_prompt: Optional[str] = None
    release_delay_days: int = 0
    release_delay_hours: int = 0
    trigger_event: TriggerEvent = TriggerEvent.MAC_GENERATED
    spark_cost: int = 0
    target_profiles: List[str] = ["all"]
    llm_config: Optional[LLMConfig] = None
    is_active: bool = True
    priority: int = 0


class TemplateUpdate(BaseModel):
    """Model for updating an existing template."""
    title: Optional[str] = None
    description: Optional[str] = None
    prompt_content: Optional[str] = None
    system_prompt: Optional[str] = None
    release_delay_days: Optional[int] = None
    release_delay_hours: Optional[int] = None
    trigger_event: Optional[TriggerEvent] = None
    spark_cost: Optional[int] = None
    target_profiles: Optional[List[str]] = None
    llm_config: Optional[LLMConfig] = None
    is_active: Optional[bool] = None
    priority: Optional[int] = None
