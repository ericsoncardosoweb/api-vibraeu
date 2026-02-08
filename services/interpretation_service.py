"""
Interpretation Service - Core business logic.
Orchestrates template loading, LLM calls, and result storage.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from loguru import logger
import json

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
            
            if current_retries < max_retries:
                # Schedule for retry
                await self.db.update_queue_status(
                    queue_id=queue_id,
                    status="pending",
                    error_log=error_msg
                )
            else:
                # Max retries reached
                await self.db.update_queue_status(
                    queue_id=queue_id,
                    status="failed",
                    error_log=f"Max retries reached. Last error: {error_msg}"
                )
            
            return {
                "success": False,
                "queue_id": queue_id,
                "error": error_msg
            }
    
    async def process_pending(self, limit: int = 10) -> Dict[str, Any]:
        """
        Process pending queue items.
        
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
        
        for item in pending_items:
            result = await self.process_queue_item(item)
            if result["success"]:
                results.append(result)
            else:
                errors.append(result.get("error", "Unknown error"))
        
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
    
    def _get_module_link(self, module_relation: str) -> str:
        """
        Mapear módulo do template para link da aplicação.
        
        Args:
            module_relation: Nome do módulo (ex: 'Mapa Astral', 'Vibrações')
            
        Returns:
            Link para a página correspondente
        """
        module_links = {
            "Mapa Astral": "https://app.vibraeu.com.br/meu-mac/mapa",
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
        
        return module_links.get(module_relation, "https://app.vibraeu.com.br/meu-mac/mapa")
