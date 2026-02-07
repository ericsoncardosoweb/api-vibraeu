"""
Luna Post-Processor Service v2

Processa interpretações brutas para:
1. Formatar em HTML
2. Extrair frase de impacto
3. Gerar dados de notificação push

Versão corrigida com parsing mais robusto.
"""

import json
import re
from typing import Dict, Any, Optional
from loguru import logger


# System prompt para forçar saída JSON
LUNA_SYSTEM_PROMPT = """Você é um assistente que SEMPRE retorna JSON válido. 
NUNCA use markdown, código ou explicações. 
Retorne APENAS o objeto JSON solicitado."""


# Prompt simplificado para melhor parsing
LUNA_PROMPT = """Revise e formate o texto abaixo seguindo estas regras:

## Formatação HTML
- Use <p> para parágrafos
- Use <strong> para destaques importantes
- Use <h3> para títulos (máximo 2-3)
- Use <blockquote><p><strong>...</strong></p></blockquote> para frase final

## Tom de Voz
- Direto e empoderador
- Conversa COM a pessoa
- Foco em ação e estratégia

## Notificação 
- Título: máximo 25 caracteres
- Texto: máximo 60 caracteres
- Desperte curiosidade

## Resposta
Retorne um JSON com esta estrutura exata:
{"text": "HTML formatado aqui", "frase": "frase de impacto", "notification": {"titulo": "titulo curto", "texto": "texto da notificacao"}}

## Texto para processar:
"""


class LunaPostProcessor:
    """Serviço de pós-processamento com Luna v2."""
    
    def __init__(self, llm_gateway):
        self.llm = llm_gateway
    
    async def process(
        self, 
        raw_text: str,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Processar texto bruto através da Luna.
        """
        if not raw_text or len(raw_text.strip()) < 50:
            logger.warning("[Luna] Texto muito curto para processar")
            return self._create_fallback(raw_text)
        
        # Config padrão: modelo econômico
        llm_config = config or {
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "temperature": 0.3,  # Menor para saída mais consistente
            "max_tokens": 4000
        }
        
        # Limitar tamanho do input para evitar problemas
        input_text = raw_text[:8000] if len(raw_text) > 8000 else raw_text
        
        prompt = LUNA_PROMPT + input_text
        
        try:
            logger.info("[Luna] Iniciando pós-processamento...")
            logger.info(f"[Luna] Input: {len(input_text)} chars")
            
            result = await self.llm.generate(
                prompt=prompt,
                config=llm_config,
                system_prompt=LUNA_SYSTEM_PROMPT
            )
            
            logger.info(f"[Luna] Resposta: {len(result)} chars")
            logger.info(f"[Luna] Preview: {repr(result[:200])}")
            
            # Tentar parsear
            parsed = self._parse_json(result)
            
            if parsed:
                logger.info("[Luna] ✓ Parse OK")
                return parsed
            else:
                logger.warning("[Luna] Parse falhou, usando fallback")
                return self._create_fallback_from_llm(result, raw_text)
            
        except Exception as e:
            logger.error(f"[Luna] Erro: {e}")
            return self._create_fallback(raw_text)
    
    def _parse_json(self, response: str) -> Optional[Dict[str, Any]]:
        """Tentar parsear JSON da resposta."""
        
        # Limpar resposta
        cleaned = response.strip()
        
        # Remover markdown se existir
        if cleaned.startswith("```"):
            # Encontrar o JSON dentro do bloco
            match = re.search(r'```(?:json)?\s*([^`]+)```', cleaned, re.DOTALL)
            if match:
                cleaned = match.group(1).strip()
        
        # Tentar encontrar objeto JSON
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned, re.DOTALL)
        if json_match:
            cleaned = json_match.group(0)
        
        try:
            data = json.loads(cleaned)
            
            # Validar estrutura
            if isinstance(data, dict) and "text" in data:
                return {
                    "text": data.get("text", ""),
                    "frase": data.get("frase", ""),
                    "notification": data.get("notification", {
                        "titulo": "Nova análise",
                        "texto": "Sua interpretação está pronta"
                    })
                }
        except json.JSONDecodeError as e:
            logger.debug(f"[Luna] JSON decode error: {e}")
        
        return None
    
    def _create_fallback_from_llm(self, llm_response: str, original: str) -> Dict[str, Any]:
        """Criar fallback usando a resposta da LLM como texto."""
        
        # Tentar extrair só o campo text se possível
        text_match = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', llm_response, re.DOTALL)
        
        if text_match:
            text = text_match.group(1)
            # Unescape
            text = text.replace('\\"', '"').replace('\\n', '\n')
            logger.info("[Luna] Extraído text via regex")
        else:
            # Usar resposta inteira com formatação básica
            text = self._format_basic_html(llm_response)
        
        return {
            "text": text,
            "frase": "",
            "notification": {
                "titulo": "Nova análise",
                "texto": "Sua interpretação está pronta"
            }
        }
    
    def _create_fallback(self, raw_text: str) -> Dict[str, Any]:
        """Criar fallback com formatação básica."""
        return {
            "text": self._format_basic_html(raw_text),
            "frase": "",
            "notification": {
                "titulo": "Nova análise",
                "texto": "Sua interpretação está pronta"
            }
        }
    
    def _format_basic_html(self, text: str) -> str:
        """Converter markdown básico para HTML."""
        if not text:
            return "<p></p>"
        
        # Já é HTML?
        if text.strip().startswith("<"):
            return text
        
        # Converter headers
        text = re.sub(r'^#{4}\s*(.+)$', r'<h4>\1</h4>', text, flags=re.MULTILINE)
        text = re.sub(r'^#{3}\s*(.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
        text = re.sub(r'^#{2}\s*(.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
        text = re.sub(r'^#{1}\s*(.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
        
        # Converter bold
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        
        # Quebras de linha duplas = novo parágrafo
        paragraphs = text.split('\n\n')
        formatted = []
        for p in paragraphs:
            p = p.strip()
            if p and not p.startswith('<h'):
                formatted.append(f"<p>{p}</p>")
            else:
                formatted.append(p)
        
        return '\n'.join(formatted)


def get_luna_processor(llm_gateway) -> LunaPostProcessor:
    """Criar instância do processador Luna."""
    return LunaPostProcessor(llm_gateway)
