"""
Notifications Router — Disparo de notificações e otimização com IA.
Endpoints:
    POST /admin/notifications/optimize — Otimizar texto com tom de voz VibraEu
    POST /admin/notifications/send-test — Enviar teste WhatsApp + Email
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from loguru import logger

from services.llm_gateway import LLMGateway
from services.whatsapp_service import get_whatsapp_service
from services.email_service import get_email_service
from services.email_templates import _base_template, _heading, _paragraph, _divider, _cta_button

router = APIRouter()


# ============================================
# Models
# ============================================

class OptimizeTextRequest(BaseModel):
    text: str


class SendTestRequest(BaseModel):
    whatsapp_number: Optional[str] = None
    email_to: Optional[str] = None
    mensagem_whatsapp: str
    mensagem_email: Optional[str] = None
    assunto_email: Optional[str] = "Notificação VibraEu"


# ============================================
# System prompt para tom de voz VibraEu
# ============================================

VIBRAEU_TONE_PROMPT = """Você é a Luna, a voz do VibraEu — uma plataforma de autoconhecimento e astrologia cabalística.

Seu tom de voz:
- **Acolhedor e empático**: Fale como uma amiga sábia que genuinamente se importa
- **Inspirador e elevado**: Use palavras que elevam a vibração e motivam transformação
- **Natural e fluido**: Evite linguagem corporativa ou fria. Seja humana.
- **Espiritual mas acessível**: Conecte conceitos astrológicos de forma leve e compreensível
- **Empoderador**: Foque em despertar o potencial interior da pessoa

Elementos que usa:
- Emojis estratégicos (✨🌟💫🌙🔮) — sem exagero
- Metáforas celestiais e naturais
- Linguagem de 2ª pessoa (você)
- Convites à ação suaves e motivadores
- Referências a ciclos, energia, vibração

NÃO faça:
- Textos muito longos (máximo 4 parágrafos)
- Linguagem excessivamente formal
- Promessas absolutas ("vai resolver tudo")
- Tons de urgência comercial

Tarefa: Reescreva o texto mantendo a intenção original mas aplicando o tom de voz do VibraEu.
Mantenha as variáveis como {nome}, {plano}, {signo} intactas.
Retorne APENAS o texto otimizado, sem explicações."""


# ============================================
# POST /admin/notifications/optimize
# ============================================

@router.post("/notifications/optimize")
async def optimize_text(req: OptimizeTextRequest):
    """Otimiza texto usando IA com tom de voz VibraEu."""
    if not req.text or len(req.text.strip()) < 10:
        raise HTTPException(status_code=400, detail="Texto muito curto para otimizar")
    
    try:
        gateway = LLMGateway.get_instance()
        
        optimized = await gateway.generate(
            prompt=req.text,
            system_prompt=VIBRAEU_TONE_PROMPT,
            config={
                "provider": "groq",
                "model": "llama-3.3-70b-versatile",
                "fallback_provider": "openai",
                "fallback_model": "gpt-4o-mini",
                "temperature": 0.7,
                "max_tokens": 1000
            }
        )
        
        return {"success": True, "optimized": optimized.strip()}
    except Exception as e:
        logger.error(f"[Notifications] AI optimize error: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao otimizar: {str(e)}")


# ============================================
# POST /admin/notifications/send-test
# ============================================

@router.post("/notifications/send-test")
async def send_test(req: SendTestRequest):
    """Envia notificação de teste por WhatsApp e/ou Email."""
    results = {}
    
    # WhatsApp
    if req.whatsapp_number:
        try:
            svc = get_whatsapp_service()
            result = await svc.send_text(req.whatsapp_number, req.mensagem_whatsapp)
            results["whatsapp"] = {"success": True, "result": result}
        except Exception as e:
            logger.error(f"[Notifications] WhatsApp test error: {e}")
            results["whatsapp"] = {"success": False, "error": str(e)}
    
    # Email
    if req.email_to:
        try:
            svc = get_email_service()
            
            # Se tem HTML do editor, envolver no template base
            if req.mensagem_email:
                email_body = _wrap_notification_email(req.mensagem_email)
            else:
                # Converter texto plain para HTML simples
                lines = req.mensagem_whatsapp.split('\n')
                body_html = "".join(_paragraph(line) for line in lines if line.strip())
                email_body = _base_template(body_html)
            
            result = await svc.send(
                to=req.email_to,
                subject=req.assunto_email or "Notificação VibraEu",
                html_body=email_body
            )
            results["email"] = {"success": True, "result": result}
        except Exception as e:
            logger.error(f"[Notifications] Email test error: {e}")
            results["email"] = {"success": False, "error": str(e)}
    
    if not req.whatsapp_number and not req.email_to:
        raise HTTPException(status_code=400, detail="Informe número WhatsApp ou email")
    
    return {
        "success": all(r.get("success") for r in results.values()),
        "results": results
    }


def _wrap_notification_email(html_content: str) -> str:
    """Envolve conteúdo HTML do editor no template base VibraEu."""
    # O conteúdo do Rich Editor já vem formatado com tags HTML
    # Só precisa envolver no wrapper visual da marca
    content = f"""
        {_heading("Comunicado VibraEu ✨")}
        {_divider()}
        <div style="color: #e0e0e0; font-size: 15px; line-height: 1.7;">
            {html_content}
        </div>
        {_divider()}
        {_cta_button("Acessar VibraEu", "https://vibraeu.com.br/inicio")}
    """
    return _base_template(content, preheader="Mensagem do VibraEu para você")
