"""
Interpretation Service - Core business logic.
Orchestrates template loading, LLM calls, and result storage.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from loguru import logger
import json
import asyncio

from .supabase_client import SupabaseService
from .llm_gateway import LLMGateway
from .variable_parser import VariableParser, get_variable_parser


class InterpretationService:
    """
    Main service for processing interpretations.
    Coordinates between database, LLM, and variable parsing.
    """
    
    def __init__(self):
        self.db = SupabaseService()
        self.llm = LLMGateway.get_instance()
        self.parser = get_variable_parser()
    
    async def trigger_by_event(
        self,
        event: str,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
        force_immediate: bool = False
    ) -> Dict[str, Any]:
        """
        Trigger interpretation generation for an event.
        
        Args:
            event: The trigger event (e.g., MAC_GENERATED)
            user_id: The user ID
            context: Optional additional context
            force_immediate: If True, schedule for now
            
        Returns:
            Dict with queued items info
        """
        # Get user profile to determine plan
        user_data = await self.db.get_user_data(user_id)
        user_plan = user_data.get("plano", "semente") if user_data else "semente"
        
        # Get matching templates
        templates = await self.db.get_templates_by_event(event, user_plan)
        
        if not templates:
            logger.info(f"No templates found for event {event}")
            return {"success": True, "queued_items": 0, "queue_ids": []}
        
        queue_ids = []
        
        for template in templates:
            # Calculate scheduled time
            if force_immediate:
                scheduled_for = datetime.utcnow()
            else:
                delay_days = template.get("release_delay_days", 0)
                delay_hours = template.get("release_delay_hours", 0)
                scheduled_for = datetime.utcnow() + timedelta(
                    days=delay_days, 
                    hours=delay_hours
                )
            
            # Add to queue
            queue_item = await self.db.add_to_queue(
                user_id=user_id,
                template_id=template["id"],
                scheduled_for=scheduled_for,
                context_data=context
            )
            
            if queue_item:
                queue_ids.append(queue_item["id"])
                logger.info(
                    f"Queued {template['custom_key']} for user {user_id}, "
                    f"scheduled for {scheduled_for}"
                )
        
        return {
            "success": True,
            "queued_items": len(queue_ids),
            "queue_ids": queue_ids
        }
    
    async def process_queue_item(
        self,
        queue_item: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process a single queue item.
        
        Args:
            queue_item: The queue item with template data
            
        Returns:
            Processing result
        """
        queue_id = queue_item["id"]
        user_id = queue_item["user_id"]
        template = queue_item.get("template", {})
        
        try:
            # Update status to processing
            await self.db.update_queue_status(queue_id, "processing")
            
            # ================================================================
            # VERIFICAR CACHE DA RESPOSTA LLM (evita desperdício de tokens)
            # ================================================================
            cached_response = queue_item.get("llm_response_cache")
            
            if cached_response:
                logger.info(f"[AIMS] ✓ Usando cache da LLM: {len(cached_response)} chars")
                raw_result = cached_response
            else:
                # Não tem cache, precisa chamar LLM
                logger.info("[AIMS] Cache vazio, chamando LLM...")
                
                # Get user data
                user_data = await self.db.get_user_data(user_id)
                mac_data = await self.db.get_user_mac(user_id)
                context_data = queue_item.get("context_data", {})
                
                # Setup parser context
                self.parser.set_context(
                    user_data=user_data,
                    mac_data=mac_data,
                    custom_data=context_data
                )
                
                # Parse prompt
                prompt_template = template.get("prompt_content", "")
                system_prompt = template.get("system_prompt")
                
                parsed_prompt = self.parser.parse(prompt_template)
                parsed_system = self.parser.parse(system_prompt) if system_prompt else None
                
                # Get LLM config
                llm_config = template.get("llm_config", {})
                if isinstance(llm_config, str):
                    llm_config = json.loads(llm_config)
                
                # Generate interpretation (raw)
                raw_result = await self.llm.generate(
                    prompt=parsed_prompt,
                    config=llm_config,
                    system_prompt=parsed_system
                )
                
                logger.info(f"[AIMS] ✓ Interpretação bruta gerada: {len(raw_result)} chars")
                
                # ================================================================
                # SALVAR CACHE IMEDIATAMENTE (antes de qualquer processamento)
                # ================================================================
                await self.db.save_llm_cache(queue_id, raw_result)
                logger.info(f"[AIMS] ✓ Cache salvo para queue {queue_id}")
            
            # ================================================================
            # PÓS-PROCESSAMENTO LUNA v2
            # ================================================================
            from .luna_processor import get_luna_processor
            
            luna = get_luna_processor(self.llm)
            processed = await luna.process(raw_result)
            
            final_text = processed.get("text") or raw_result
            frase = processed.get("frase") or ""
            notification_data = processed.get("notification") or {}
            
            logger.info(f"[Luna] ✓ Processado: {len(final_text)} chars")
            
            # Save to user_infos_data for frontend access
            custom_key = template.get("custom_key", "aims-interpretation")
            logger.info(f"[AIMS] Salvando na user_infos_data: user_id={user_id}, action={custom_key}")
            
            save_result = await self.db.save_user_info(
                user_id=user_id,
                action=custom_key,
                metadata=final_text  # Salva o texto formatado
            )
            
            if save_result:
                logger.info(f"[AIMS] ✓ Salvo com sucesso na user_infos_data!")
            else:
                logger.warning(f"[AIMS] ⚠ Falha ao salvar na user_infos_data")
            
            # ================================================================
            # CRIAR NOTIFICAÇÃO
            # ================================================================
            try:
                module_relation = template.get("module_relation", "Mapa Astral")
                notification_link = self._get_module_link(module_relation)
                
                await self.db.create_notification(
                    user_id=user_id,
                    title=notification_data.get("titulo", "Nova análise"),
                    message=notification_data.get("texto", f"Sua análise de {custom_key.replace('-', ' ').title()} está pronta"),
                    link=notification_link
                )
                logger.info(f"[AIMS] ✓ Notificação criada")
            except Exception as notif_error:
                logger.warning(f"[AIMS] ⚠ Falha ao criar notificação: {notif_error}")
            
            # Update with success
            await self.db.update_queue_status(
                queue_id=queue_id,
                status="completed",
                result_content=final_text
            )
            
            # ================================================================
            # LIMPAR CACHE DA LLM (processamento concluído)
            # ================================================================
            await self.db.clear_llm_cache(queue_id)
            
            logger.info(f"Successfully processed queue item {queue_id}")
            
            return {
                "success": True,
                "queue_id": queue_id,
                "template_key": template.get("custom_key"),
                "result_length": len(final_text)
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error processing queue item {queue_id}: {error_msg}")
            
            # Check retry count
            current_retries = queue_item.get("retry_count", 0)
            max_retries = queue_item.get("max_retries", 3)
            
            # Erros de autenticação/autorização não devem ser re-tentados
            is_auth_error = "401" in error_msg or "Unauthorized" in error_msg or "403" in error_msg
            
            if is_auth_error or current_retries >= max_retries:
                # Erro fatal ou max retries — marcar como failed
                fail_reason = f"Auth error (não re-tentável): {error_msg}" if is_auth_error else f"Max retries ({max_retries}) reached. Last error: {error_msg}"
                await self.db.update_queue_status(
                    queue_id=queue_id,
                    status="failed",
                    error_log=fail_reason
                )
            else:
                # Schedule for retry (incrementa retry_count)
                await self.db.update_queue_status(
                    queue_id=queue_id,
                    status="pending",
                    error_log=error_msg,
                    increment_retry=True
                )
            
            return {
                "success": False,
                "queue_id": queue_id,
                "error": error_msg
            }
    
    async def process_pending(self, limit: int = 10) -> Dict[str, Any]:
        """
        Process pending queue items with throttling.
        
        Args:
            limit: Maximum items to process
            
        Returns:
            Processing results summary
        """
        pending_items = await self.db.get_pending_queue_items(limit)
        
        if not pending_items:
            return {
                "success": True,
                "processed": 0,
                "results": []
            }
        
        results = []
        errors = []
        consecutive_errors = 0
        
        for i, item in enumerate(pending_items):
            # Throttle: esperar entre items (exceto o primeiro)
            if i > 0:
                await asyncio.sleep(3)  # 3s de intervalo entre chamadas LLM
            
            result = await self.process_queue_item(item)
            if result["success"]:
                results.append(result)
                consecutive_errors = 0
            else:
                errors.append(result.get("error", "Unknown error"))
                consecutive_errors += 1
                
                # Se 3 erros consecutivos, parar o batch (provavelmente problema sistêmico)
                if consecutive_errors >= 3:
                    logger.warning(f"[AIMS] ⚠ {consecutive_errors} erros consecutivos — parando batch para evitar desperdício")
                    break
        
        return {
            "success": len(errors) == 0,
            "processed": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors
        }
    
    async def force_process(
        self,
        user_id: str,
        template_key: str
    ) -> Dict[str, Any]:
        """
        Force immediate processing for a specific template.
        
        Args:
            user_id: The user ID
            template_key: The template custom_key
            
        Returns:
            Processing result
        """
        # Get template
        template = await self.db.get_template_by_key(template_key)
        if not template:
            return {"success": False, "error": f"Template {template_key} not found"}
        
        # Create queue item
        queue_item = await self.db.add_to_queue(
            user_id=user_id,
            template_id=template["id"],
            scheduled_for=datetime.utcnow()
        )
        
        if not queue_item:
            return {"success": False, "error": "Failed to create queue item"}
        
        # Add template data for processing
        queue_item["template"] = template
        
        # Process immediately
        return await self.process_queue_item(queue_item)

    async def sync_user_interpretations(
        self,
        user_id: str
    ) -> Dict[str, Any]:
        """
        Sync interpretations for a user.
        
        Checks which MAC templates should have been released by now
        but have no content in user_infos_data. Regenerates missing ones
        sequentially with 10s throttle between each.
        
        Called by frontend on login/MAC load.
        
        Args:
            user_id: The user ID
            
        Returns:
            Dict with missing, generated, failed counts and details
        """
        logger.info(f"[AIMS Sync] Starting sync for user {user_id}")
        
        # 1. Get user's MAC
        mac_data = await self.db.get_user_mac(user_id)
        if not mac_data:
            logger.info(f"[AIMS Sync] No MAC found for user {user_id}")
            return {"success": True, "missing": 0, "generated": 0, "message": "No MAC found"}
        
        mac_created_at = mac_data.get("created_at")
        if not mac_created_at:
            mac_created_at = datetime.utcnow().isoformat()
        
        # Parse MAC creation date
        if isinstance(mac_created_at, str):
            try:
                mac_date = datetime.fromisoformat(mac_created_at.replace("Z", "+00:00")).replace(tzinfo=None)
            except:
                mac_date = datetime.utcnow()
        else:
            mac_date = mac_created_at
        
        # 2. Get ALL active MAC templates (ignore target_profiles filter)
        try:
            response = self.db.client.table("adv_interpretation_templates") \
                .select("*") \
                .eq("trigger_event", "MAC_GENERATED") \
                .eq("is_active", True) \
                .execute()
            templates = response.data or []
        except Exception as e:
            logger.error(f"[AIMS Sync] Error fetching templates: {e}")
            return {"success": False, "error": str(e)}
        
        if not templates:
            logger.info("[AIMS Sync] No MAC_GENERATED templates found")
            return {"success": True, "missing": 0, "generated": 0, "message": "No templates"}
        
        # 3. Get existing content for this user
        try:
            existing_response = self.db.client.table("user_infos_data") \
                .select("action") \
                .eq("user_id", user_id) \
                .execute()
            existing_actions = set()
            for item in (existing_response.data or []):
                # Only count as existing if metadata is not null/empty
                existing_actions.add(item["action"])
        except Exception as e:
            logger.error(f"[AIMS Sync] Error fetching existing content: {e}")
            existing_actions = set()
        
        # 4. Check which templates should be released but have no content
        now = datetime.utcnow()
        missing_templates = []
        
        for template in templates:
            custom_key = template.get("custom_key", "")
            delay_days = template.get("release_delay_days", 0) or 0
            delay_hours = template.get("release_delay_hours", 0) or 0
            
            release_date = mac_date + timedelta(days=delay_days, hours=delay_hours)
            
            if release_date <= now and custom_key not in existing_actions:
                missing_templates.append({
                    "template": template,
                    "custom_key": custom_key,
                    "was_due_since": release_date.isoformat()
                })
        
        if not missing_templates:
            logger.info(f"[AIMS Sync] All interpretations up to date for user {user_id}")
            return {
                "success": True, 
                "missing": 0, 
                "generated": 0, 
                "total_templates": len(templates),
                "existing": len(existing_actions),
                "message": "All synced"
            }
        
        logger.info(
            f"[AIMS Sync] Found {len(missing_templates)} missing interpretations for user {user_id}: "
            f"{[m['custom_key'] for m in missing_templates]}"
        )
        
        # 5. Generate missing interpretations sequentially with throttle
        generated = 0
        failed = 0
        results = []
        
        for i, missing in enumerate(missing_templates):
            template = missing["template"]
            custom_key = missing["custom_key"]
            
            # Throttle: 10s between each (except first)
            if i > 0:
                logger.info(f"[AIMS Sync] Throttle: waiting 10s before next...")
                await asyncio.sleep(10)
            
            try:
                logger.info(f"[AIMS Sync] Generating {custom_key} ({i+1}/{len(missing_templates)})")
                
                # Create queue item and process immediately
                queue_item = await self.db.add_to_queue(
                    user_id=user_id,
                    template_id=template["id"],
                    scheduled_for=datetime.utcnow()
                )
                
                if not queue_item:
                    raise Exception("Failed to create queue item")
                
                queue_item["template"] = template
                result = await self.process_queue_item(queue_item)
                
                if result.get("success"):
                    generated += 1
                    results.append({"key": custom_key, "status": "generated"})
                    logger.info(f"[AIMS Sync] ✅ Generated {custom_key}")
                else:
                    failed += 1
                    results.append({"key": custom_key, "status": "failed", "error": result.get("error")})
                    logger.error(f"[AIMS Sync] ❌ Failed {custom_key}: {result.get('error')}")
                    
            except Exception as e:
                failed += 1
                results.append({"key": custom_key, "status": "failed", "error": str(e)})
                logger.error(f"[AIMS Sync] ❌ Exception for {custom_key}: {e}")
        
        logger.info(
            f"[AIMS Sync] Sync complete for {user_id}: "
            f"{generated} generated, {failed} failed of {len(missing_templates)} missing"
        )
        
        return {
            "success": failed == 0,
            "missing": len(missing_templates),
            "generated": generated,
            "failed": failed,
            "results": results
        }

    def _get_module_link(self, module_relation: str) -> str:
        """
        Mapear módulo do template para link da aplicação.
        
        Args:
            module_relation: Nome do módulo (ex: 'Mapa Astral', 'Vibrações')
            
        Returns:
            Link para a página correspondente
        """
        module_links = {
            "Mapa Astral": "https://app.vibraeu.com.br/mac-interpretacoes",
            "Vibrações": "https://app.vibraeu.com.br/vibracoes",
            "Perfil Comportamental": "https://app.vibraeu.com.br/perfil-comportamental",
            "Roda da Vida": "https://app.vibraeu.com.br/roda-da-vida",
            "Diário de Bordo": "https://app.vibraeu.com.br/diario",
            "Mantra Pessoal": "https://app.vibraeu.com.br/mantra",
            "Teste de Compatibilidade": "https://app.vibraeu.com.br/compatibilidade",
            "Campo de Expressão": "https://app.vibraeu.com.br/campo-expressao",
            "Metas e Conquistas": "https://app.vibraeu.com.br/metas",
            "Centelhas": "https://app.vibraeu.com.br/centelhas",
            "Geral (Sistema)": "https://app.vibraeu.com.br/",
        }
        
        return module_links.get(module_relation, "https://app.vibraeu.com.br/mac-interpretacoes")
