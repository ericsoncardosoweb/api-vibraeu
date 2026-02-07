"""
AIMS Execution Engine

Processes pending items from the execution queue:
1. Fetches pending queue items
2. Retrieves user data and MAC
3. Either:
   a. Substitutes variables in prompt and calls LLM (mode: llm)
   b. Dispatches webhook to external endpoint (mode: webhook)
4. Saves result as interpretation or logs webhook response
"""

import os
import json
import re
from datetime import datetime
from typing import Dict, Any, Optional, List
from loguru import logger

from services.supabase_client import SupabaseService


class AIMSEngine:
    """Engine for processing AIMS interpretation queue."""
    
    def __init__(self):
        self.supabase = SupabaseService()
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.groq_api_key = os.getenv("GROQ_API_KEY")
    
    async def process_queue(self, limit: int = 10) -> Dict[str, Any]:
        """
        Process pending items from the queue.
        
        Returns:
            Dict with processed, failed, and skipped counts
        """
        logger.info("Starting AIMS queue processing...")
        
        # Fetch pending items that are scheduled for now or earlier
        now = datetime.utcnow().isoformat()
        
        response = self.supabase.client.table("adv_execution_queue") \
            .select("*, template:adv_interpretation_templates(*)") \
            .eq("status", "pending") \
            .lte("scheduled_for", now) \
            .order("created_at") \
            .limit(limit) \
            .execute()
        
        items = response.data or []
        
        if not items:
            logger.info("No pending items in queue")
            return {"processed": 0, "failed": 0, "skipped": 0}
        
        logger.info(f"Found {len(items)} items to process")
        
        processed = 0
        failed = 0
        skipped = 0
        
        for item in items:
            try:
                result = await self.process_item(item)
                if result.get("success"):
                    processed += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Error processing item {item['id']}: {e}")
                await self._update_queue_status(item["id"], "failed", str(e))
                failed += 1
        
        logger.info(f"Queue processing complete: {processed} processed, {failed} failed, {skipped} skipped")
        
        return {
            "processed": processed,
            "failed": failed,
            "skipped": skipped
        }
    
    async def process_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single queue item."""
        queue_id = item["id"]
        user_id = item["user_id"]
        template = item.get("template", {})
        
        logger.info(f"Processing queue item {queue_id} for user {user_id}")
        
        # Mark as processing
        await self._update_queue_status(queue_id, "processing")
        
        try:
            # 1. Get user data
            user_data = await self.supabase.get_user_data(user_id)
            if not user_data:
                raise Exception(f"User not found: {user_id}")
            
            # 2. Get MAC data
            mac_data = await self.supabase.get_user_mac(user_id)
            
            # 3. Build context with all variable data
            context = await self._build_context(user_data, mac_data, item.get("context_data", {}))
            
            # Check execution mode
            execution_mode = template.get("execution_mode", "llm")
            custom_key = template.get("custom_key", "aims-interpretation")
            
            if execution_mode == "webhook":
                # WEBHOOK MODE: Dispatch to external endpoint
                logger.info(f"[AIMS] Execution mode: WEBHOOK for template {custom_key}")
                
                webhook_config = template.get("webhook_config", {})
                webhook_response = await self._call_webhook(
                    user_data=user_data,
                    mac_data=mac_data,
                    context=context,
                    template=template,
                    webhook_config=webhook_config
                )
                
                if not webhook_response.get("success"):
                    raise Exception(webhook_response.get("error", "Webhook call failed"))
                
                # Update queue as completed
                await self._update_queue_status(
                    queue_id, 
                    "completed",
                    result={
                        "action": custom_key,
                        "mode": "webhook",
                        "status_code": webhook_response.get("status_code"),
                        "response_preview": str(webhook_response.get("response_body", ""))[:500]
                    }
                )
                
                logger.info(f"[AIMS] ✓ Webhook executed successfully for {custom_key}")
                return {"success": True, "action": custom_key, "mode": "webhook"}
            
            else:
                # LLM MODE: Process with AI
                logger.info(f"[AIMS] Execution mode: LLM for template {custom_key}")
                
                # 4. Substitute variables in prompt
                prompt_content = template.get("prompt_content", "")
                system_prompt = template.get("system_prompt", "")
                
                final_prompt = self._substitute_variables(prompt_content, context)
                final_system = self._substitute_variables(system_prompt, context) if system_prompt else None
                
                logger.debug(f"Prompt after substitution: {final_prompt[:200]}...")
                
                # 5. Call LLM
                llm_config = template.get("llm_config", {})
                llm_response = await self._call_llm(
                    prompt=final_prompt,
                    system_prompt=final_system,
                    config=llm_config
                )
                
                if not llm_response.get("success"):
                    raise Exception(llm_response.get("error", "LLM call failed"))
                
                # 6. Save interpretation result to user_infos_data
                interpretation_content = llm_response.get("content", "")
                
                logger.info(f"[AIMS] Preparando para salvar na user_infos_data")
                logger.info(f"[AIMS] user_id: {user_id}")
                logger.info(f"[AIMS] action (custom_key): {custom_key}")
                logger.info(f"[AIMS] content length: {len(interpretation_content)} chars")
                logger.info(f"[AIMS] content preview: {interpretation_content[:200]}...")
                
                # Formato compatível com user_infos_data
                user_info_data = {
                    "user_id": user_id,
                    "action": custom_key,
                    "metadata": interpretation_content,
                    "updated_at": datetime.utcnow().isoformat()
                }
                
                logger.info(f"[AIMS] Executando upsert na user_infos_data...")
                
                # Upsert na user_infos_data
                save_response = self.supabase.client.table("user_infos_data") \
                    .upsert(user_info_data, on_conflict="user_id,action") \
                    .execute()
                
                logger.info(f"[AIMS] Resposta do upsert: {save_response}")
                logger.info(f"[AIMS] save_response.data: {save_response.data}")
                
                if not save_response.data:
                    logger.error(f"[AIMS] Falha ao salvar - save_response.data está vazio!")
                    raise Exception("Failed to save interpretation to user_infos_data")
                
                logger.info(f"[AIMS] ✓ Salvo com sucesso na user_infos_data: action={custom_key}")
                
                # 7. Update queue as completed
                await self._update_queue_status(
                    queue_id, 
                    "completed",
                    result={
                        "action": custom_key,
                        "mode": "llm",
                        "tokens_used": llm_response.get("tokens_used", 0)
                    }
                )
                
                logger.info(f"Successfully processed item {queue_id}")
                
                return {"success": True, "action": custom_key, "mode": "llm"}
            
        except Exception as e:
            logger.error(f"Failed to process item {queue_id}: {e}")
            await self._update_queue_status(queue_id, "failed", str(e))
            return {"success": False, "error": str(e)}
    
    async def _build_context(
        self, 
        user_data: Dict[str, Any], 
        mac_data: Optional[Dict[str, Any]],
        context_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build the context dictionary for variable substitution."""
        
        context = {
            # User variables
            "user": {
                "profile": json.dumps(user_data, ensure_ascii=False, default=str),
                "id": user_data.get("id", ""),
                "name": user_data.get("name", user_data.get("full_name", "")),
                "nickname": user_data.get("nickname", user_data.get("name", "").split()[0] if user_data.get("name") else ""),
                "email": user_data.get("email", ""),
                "sexo": user_data.get("sexo", user_data.get("gender", "")),
                "birth_date": user_data.get("birth_date", ""),
            },
            # MAC variables
            "mac": {
                "full": json.dumps(mac_data, ensure_ascii=False, default=str) if mac_data else "{}",
            },
            # Context variables
            "context": {
                "today": datetime.now().strftime("%Y-%m-%d"),
                "timestamp": datetime.now().isoformat(),
                **context_data
            }
        }
        
        # Add individual MAC fields if available
        if mac_data:
            context["mac"].update({
                "sun": mac_data.get("sol_signo", ""),
                "sun_sign": mac_data.get("sol_signo", ""),
                "moon": mac_data.get("lua_signo", ""),
                "moon_sign": mac_data.get("lua_signo", ""),
                "ascendant": mac_data.get("ascendente_signo", ""),
                "ascendant_sign": mac_data.get("ascendente_signo", ""),
                "mc": mac_data.get("mc_signo", ""),
                "mc_sign": mac_data.get("mc_signo", ""),
            })
            
            # Add planetary data
            planetas = mac_data.get("planetas", [])
            if isinstance(planetas, list):
                for planeta in planetas:
                    planet_name = planeta.get("planeta", "").lower()
                    if planet_name:
                        context["mac"][planet_name] = planeta.get("signo", "")
                        context["mac"][f"{planet_name}_full"] = json.dumps(planeta, ensure_ascii=False)
        
        return context
    
    async def _call_webhook(
        self,
        user_data: Dict[str, Any],
        mac_data: Optional[Dict[str, Any]],
        context: Dict[str, Any],
        template: Dict[str, Any],
        webhook_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Call external webhook endpoint with user data.
        
        Args:
            user_data: User information
            mac_data: Astrological map data
            context: Built context with variables
            template: Template configuration
            webhook_config: Webhook configuration (endpoint, method, headers)
            
        Returns:
            Dict with success status, status_code, and response_body
        """
        import httpx
        
        endpoint = webhook_config.get("endpoint", "")
        method = webhook_config.get("method", "POST").upper()
        custom_headers = webhook_config.get("headers", {})
        include_user_data = webhook_config.get("include_user_data", True)
        include_context_data = webhook_config.get("include_context_data", True)
        
        if not endpoint:
            return {"success": False, "error": "No endpoint configured"}
        
        logger.info(f"[AIMS Webhook] Calling {method} {endpoint}")
        
        # Build payload
        payload = {
            "template_id": template.get("custom_key", ""),
            "template_title": template.get("title", ""),
            "trigger_event": template.get("trigger_event", ""),
            "target_profiles": template.get("target_profiles", []),
            "metadata": {
                "executed_at": datetime.utcnow().isoformat(),
                "module": template.get("module_relation", ""),
                "aims_version": "1.0"
            }
        }
        
        # Build user object
        user_payload = {
            "id": user_data.get("id", ""),
            "name": user_data.get("name", user_data.get("full_name", "")),
            "email": user_data.get("email", ""),
        }
        
        if include_user_data:
            user_payload["profile"] = {
                "nickname": user_data.get("nickname", ""),
                "birth_date": user_data.get("birth_date", ""),
                "birth_time": user_data.get("birth_time", ""),
                "birth_city": user_data.get("birth_city", ""),
                "sexo": user_data.get("sexo", user_data.get("gender", "")),
                "plan": user_data.get("plano", user_data.get("plan", "free")),
            }
        
        if include_context_data and mac_data:
            user_payload["context"] = {
                "mac": {
                    "sol": mac_data.get("sol_signo", ""),
                    "lua": mac_data.get("lua_signo", ""),
                    "ascendente": mac_data.get("ascendente_signo", ""),
                    "mc": mac_data.get("mc_signo", ""),
                    "planetas": mac_data.get("planetas", []),
                    "casas": mac_data.get("casas", []),
                }
            }
        
        payload["users"] = [user_payload]
        
        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AIMS-Engine/1.0",
            "X-AIMS-Template": template.get("custom_key", ""),
        }
        
        # Merge custom headers (ensure they're valid)
        if isinstance(custom_headers, dict):
            for key, value in custom_headers.items():
                if isinstance(key, str) and isinstance(value, str):
                    headers[key] = value
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                if method == "PUT":
                    response = await client.put(endpoint, json=payload, headers=headers)
                elif method == "PATCH":
                    response = await client.patch(endpoint, json=payload, headers=headers)
                else:
                    response = await client.post(endpoint, json=payload, headers=headers)
                
                status_code = response.status_code
                
                # Try to parse response as JSON
                try:
                    response_body = response.json()
                except:
                    response_body = response.text
                
                logger.info(f"[AIMS Webhook] Response: {status_code}")
                
                # Consider 2xx status codes as success
                if 200 <= status_code < 300:
                    return {
                        "success": True,
                        "status_code": status_code,
                        "response_body": response_body
                    }
                else:
                    logger.warning(f"[AIMS Webhook] Non-success status: {status_code} - {response_body}")
                    return {
                        "success": False,
                        "error": f"Webhook returned status {status_code}",
                        "status_code": status_code,
                        "response_body": response_body
                    }
                    
        except httpx.TimeoutException:
            logger.error(f"[AIMS Webhook] Timeout calling {endpoint}")
            return {"success": False, "error": "Webhook request timed out"}
        except httpx.RequestError as e:
            logger.error(f"[AIMS Webhook] Request error: {e}")
            return {"success": False, "error": f"Request error: {str(e)}"}
        except Exception as e:
            logger.error(f"[AIMS Webhook] Unexpected error: {e}")
            return {"success": False, "error": str(e)}
    
    def _substitute_variables(self, text: str, context: Dict[str, Any]) -> str:
        """
        Substitute variables in text.
        Variables use format: @category.variable
        Example: @user.name, @mac.full, @context.today
        """
        if not text:
            return text
        
        # Pattern: @category.variable (with optional nested paths)
        pattern = r"@(\w+)\.(\w+(?:\.\w+)*)"
        
        def replace_var(match):
            category = match.group(1)
            path = match.group(2)
            
            try:
                # Get category data
                category_data = context.get(category, {})
                
                # Navigate path (supports nested: @user.profile.name)
                parts = path.split(".")
                value = category_data
                
                for part in parts:
                    if isinstance(value, dict):
                        value = value.get(part, "")
                    else:
                        value = ""
                        break
                
                # Convert to string if needed
                if isinstance(value, (dict, list)):
                    return json.dumps(value, ensure_ascii=False, default=str)
                
                return str(value) if value else match.group(0)
                
            except Exception as e:
                logger.warning(f"Error substituting variable {match.group(0)}: {e}")
                return match.group(0)
        
        return re.sub(pattern, replace_var, text)
    
    async def _call_llm(
        self, 
        prompt: str, 
        system_prompt: Optional[str],
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Call the LLM API (OpenAI or Groq)."""
        
        provider = config.get("provider", "openai")
        model = config.get("model", "gpt-4.1-mini")
        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("max_tokens", 2000)
        
        logger.info(f"Calling LLM: {provider}/{model}")
        
        try:
            if provider == "groq":
                return await self._call_groq(prompt, system_prompt, model, temperature, max_tokens)
            else:
                return await self._call_openai(prompt, system_prompt, model, temperature, max_tokens)
        except Exception as e:
            # Try fallback if configured
            fallback_provider = config.get("fallback_provider")
            fallback_model = config.get("fallback_model")
            
            if fallback_provider and fallback_model:
                logger.warning(f"Primary LLM failed, trying fallback: {fallback_provider}/{fallback_model}")
                try:
                    if fallback_provider == "groq":
                        return await self._call_groq(prompt, system_prompt, fallback_model, temperature, max_tokens)
                    else:
                        return await self._call_openai(prompt, system_prompt, fallback_model, temperature, max_tokens)
                except Exception as fallback_error:
                    logger.error(f"Fallback LLM also failed: {fallback_error}")
            
            return {"success": False, "error": str(e)}
    
    async def _call_openai(
        self, 
        prompt: str, 
        system_prompt: Optional[str],
        model: str,
        temperature: float,
        max_tokens: int
    ) -> Dict[str, Any]:
        """Call OpenAI API."""
        import httpx
        
        if not self.openai_api_key:
            raise Exception("OPENAI_API_KEY not configured")
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openai_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"OpenAI API error: {response.status_code} - {response.text}")
            
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            tokens_used = data.get("usage", {}).get("total_tokens", 0)
            
            return {
                "success": True,
                "content": content,
                "tokens_used": tokens_used
            }
    
    async def _call_groq(
        self, 
        prompt: str, 
        system_prompt: Optional[str],
        model: str,
        temperature: float,
        max_tokens: int
    ) -> Dict[str, Any]:
        """Call Groq API."""
        import httpx
        
        if not self.groq_api_key:
            raise Exception("GROQ_API_KEY not configured")
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.groq_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"Groq API error: {response.status_code} - {response.text}")
            
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            tokens_used = data.get("usage", {}).get("total_tokens", 0)
            
            return {
                "success": True,
                "content": content,
                "tokens_used": tokens_used
            }
    
    async def _update_queue_status(
        self, 
        queue_id: str, 
        status: str, 
        error_message: str = None,
        result: Dict[str, Any] = None
    ):
        """Update queue item status."""
        update_data = {
            "status": status,
            "updated_at": datetime.utcnow().isoformat()
        }
        
        if status == "processing":
            update_data["started_at"] = datetime.utcnow().isoformat()
        elif status == "completed":
            update_data["completed_at"] = datetime.utcnow().isoformat()
            if result:
                update_data["result_data"] = result
        elif status == "failed":
            update_data["error_message"] = error_message
            update_data["retry_count"] = 1  # TODO: Increment on retry
        
        self.supabase.client.table("adv_execution_queue") \
            .update(update_data) \
            .eq("id", queue_id) \
            .execute()


# Singleton instance
_engine_instance = None

def get_engine() -> AIMSEngine:
    """Get or create the AIMS engine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = AIMSEngine()
    return _engine_instance
