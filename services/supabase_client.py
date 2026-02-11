"""
Supabase client service for database operations.
"""

from supabase import create_client, Client
from functools import lru_cache
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from loguru import logger
import uuid

from config import get_settings


@lru_cache()
def get_supabase_client() -> Client:
    """Get cached Supabase client instance."""
    settings = get_settings()
    
    # Simple create_client - no options to avoid gotrue proxy bug
    # https://github.com/supabase-community/supabase-py/issues/831
    return create_client(settings.supabase_url, settings.supabase_service_key)


class SupabaseService:
    """Service for Supabase database operations."""
    
    def __init__(self):
        self.client = get_supabase_client()
    
    # =========================================================================
    # TEMPLATES
    # =========================================================================
    
    async def get_templates_by_event(
        self, 
        event: str, 
        target_profile: str = "all"
    ) -> List[Dict[str, Any]]:
        """Get active templates for a specific trigger event."""
        try:
            response = self.client.table("adv_interpretation_templates") \
                .select("*") \
                .eq("trigger_event", event) \
                .eq("is_active", True) \
                .execute()
            
            # Filter by target profile
            templates = response.data or []
            filtered = [
                t for t in templates 
                if "all" in t.get("target_profiles", []) 
                or target_profile in t.get("target_profiles", [])
            ]
            
            return filtered
        except Exception as e:
            logger.error(f"Error fetching templates: {e}")
            return []
    
    async def get_template_by_key(self, custom_key: str) -> Optional[Dict[str, Any]]:
        """Get a template by its custom key."""
        try:
            response = self.client.table("adv_interpretation_templates") \
                .select("*") \
                .eq("custom_key", custom_key) \
                .limit(1) \
                .execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error fetching template {custom_key}: {e}")
            return None
    
    async def get_template_by_id(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Get a template by ID."""
        try:
            response = self.client.table("adv_interpretation_templates") \
                .select("*") \
                .eq("id", template_id) \
                .limit(1) \
                .execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error fetching template {template_id}: {e}")
            return None
    
    # =========================================================================
    # QUEUE
    # =========================================================================
    
    async def add_to_queue(
        self,
        user_id: str,
        template_id: str,
        scheduled_for: Optional[datetime] = None,
        context_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Add an item to the execution queue."""
        try:
            data = {
                "user_id": user_id,
                "template_id": template_id,
                "scheduled_for": (scheduled_for or datetime.utcnow()).isoformat(),
                "status": "pending",
                "context_data": context_data or {}
            }
            
            response = self.client.table("adv_execution_queue") \
                .insert(data) \
                .execute()
            
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error adding to queue: {e}")
            return None
    
    async def get_pending_queue_items(
        self, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get pending queue items ready for processing."""
        try:
            now = datetime.utcnow().isoformat()
            
            response = self.client.table("adv_execution_queue") \
                .select("*, template:adv_interpretation_templates(*)") \
                .in_("status", ["pending", "retry_pending"]) \
                .lte("scheduled_for", now) \
                .order("scheduled_for") \
                .limit(limit) \
                .execute()
            
            return response.data or []
        except Exception as e:
            logger.error(f"Error fetching pending items: {e}")
            return []
    
    async def update_queue_status(
        self,
        queue_id: str,
        status: str,
        result_content: Optional[str] = None,
        error_log: Optional[str] = None
    ) -> bool:
        """Update queue item status."""
        try:
            # retry_pending é convertido para pending no DB, mas incrementa retry_count
            actual_status = "pending" if status == "retry_pending" else status
            
            update_data = {
                "status": actual_status,
                "updated_at": datetime.utcnow().isoformat()
            }
            
            if status == "processing":
                update_data["processing_started_at"] = datetime.utcnow().isoformat()
            elif status == "completed":
                update_data["completed_at"] = datetime.utcnow().isoformat()
                update_data["result_content"] = result_content
            elif status in ("failed", "retry_pending"):
                update_data["error_log"] = error_log
                # Increment retry count on both failed and retry_pending
                item = await self.get_queue_item(queue_id)
                if item:
                    update_data["retry_count"] = item.get("retry_count", 0) + 1
            
            self.client.table("adv_execution_queue") \
                .update(update_data) \
                .eq("id", queue_id) \
                .execute()
            
            return True
        except Exception as e:
            logger.error(f"Error updating queue status: {e}")
            return False
    
    async def get_queue_item(self, queue_id: str) -> Optional[Dict[str, Any]]:
        """Get a queue item by ID."""
        try:
            response = self.client.table("adv_execution_queue") \
                .select("*") \
                .eq("id", queue_id) \
                .limit(1) \
                .execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error fetching queue item: {e}")
            return None
    
    # =========================================================================
    # USER DATA
    # =========================================================================
    
    async def get_user_data(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user profile data."""
        try:
            response = self.client.table("profiles") \
                .select("*") \
                .eq("id", user_id) \
                .limit(1) \
                .execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error fetching user data: {e}")
            return None
    
    async def get_user_mac(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user's astral map data."""
        try:
            response = self.client.table("mapas_astrais") \
                .select("*") \
                .eq("user_id", user_id) \
                .limit(1) \
                .execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error fetching MAC data: {e}")
            return None
    
    # =========================================================================
    # VARIABLES
    # =========================================================================
    
    async def get_available_variables(self) -> List[Dict[str, Any]]:
        """Get all available variables for prompts."""
        try:
            response = self.client.table("adv_interpretation_variables") \
                .select("*") \
                .eq("is_active", True) \
                .order("sort_order") \
                .execute()
            return response.data or []
        except Exception as e:
            logger.error(f"Error fetching variables: {e}")
            return []

    # =========================================================================
    # USER INFOS DATA (para interpretações)
    # =========================================================================
    
    async def save_user_info(
        self, 
        user_id: str, 
        action: str, 
        metadata: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Save/update interpretation data in user_infos_data.
        Uses upsert to update if exists, insert if not.
        
        Args:
            user_id: User ID
            action: Action/slug (e.g., mac-sol, mac-lua)
            metadata: Content to save
            
        Returns:
            Saved data or None on error
        """
        try:
            from datetime import datetime
            
            data = {
                "user_id": user_id,
                "action": action,
                "metadata": metadata,
                "updated_at": datetime.utcnow().isoformat()
            }
            
            logger.info(f"[DB] Upserting user_infos_data: user_id={user_id}, action={action}")
            
            response = self.client.table("user_infos_data") \
                .upsert(data, on_conflict="user_id,action") \
                .execute()
            
            if response.data:
                logger.info(f"[DB] ✓ Upsert successful, returned: {len(response.data)} row(s)")
                return response.data[0]
            else:
                logger.warning(f"[DB] Upsert returned no data")
                return None
                
        except Exception as e:
            logger.error(f"[DB] Error saving user_info: {e}")
            return None

    # =========================================================================
    # NOTIFICATIONS
    # =========================================================================
    
    async def create_notification(
        self, 
        user_id: str, 
        title: str, 
        message: str,
        link: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a notification for a user.
        
        Args:
            user_id: User ID
            title: Notification title
            message: Notification message
            link: Optional link to navigate to
            
        Returns:
            Created notification or None on error
        """
        try:
            from datetime import datetime
            
            data = {
                "user_id": user_id,
                "title": title,
                "message": message,
                "link": link,
                "is_read": False,
                "created_at": datetime.utcnow().isoformat()
            }
            
            logger.info(f"[DB] Creating notification for user {user_id}: {title}")
            
            response = self.client.table("notifications") \
                .insert(data) \
                .execute()
            
            if response.data:
                logger.info(f"[DB] ✓ Notification created successfully")
                return response.data[0]
            else:
                logger.warning(f"[DB] Notification insert returned no data")
                return None
                
        except Exception as e:
            logger.error(f"[DB] Error creating notification: {e}")
            return None

    # =========================================================================
    # LLM RESPONSE CACHE
    # =========================================================================
    
    async def save_llm_cache(
        self, 
        queue_id: str, 
        llm_response: str
    ) -> bool:
        """
        Save LLM response to queue item as cache.
        This prevents re-calling the LLM if post-processing fails.
        
        Args:
            queue_id: Queue item ID
            llm_response: Raw LLM response to cache
            
        Returns:
            True if saved successfully
        """
        try:
            self.client.table("adv_execution_queue") \
                .update({
                    "llm_response_cache": llm_response,
                    "updated_at": datetime.utcnow().isoformat()
                }) \
                .eq("id", queue_id) \
                .execute()
            
            logger.info(f"[DB] ✓ LLM cache saved for queue {queue_id}")
            return True
            
        except Exception as e:
            logger.error(f"[DB] Error saving LLM cache: {e}")
            return False

    async def clear_llm_cache(self, queue_id: str) -> bool:
        """
        Clear LLM cache from queue item after successful processing.
        
        Args:
            queue_id: Queue item ID
            
        Returns:
            True if cleared successfully
        """
        try:
            self.client.table("adv_execution_queue") \
                .update({
                    "llm_response_cache": None,
                    "updated_at": datetime.utcnow().isoformat()
                }) \
                .eq("id", queue_id) \
                .execute()
            
            logger.info(f"[DB] ✓ LLM cache cleared for queue {queue_id}")
            return True
            
        except Exception as e:
            logger.error(f"[DB] Error clearing LLM cache: {e}")
            return False
