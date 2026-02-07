"""
Messaging Router — Endpoints HTTP para WhatsApp e Email.
Protegido por API Key (frontend usa via apiClient).

Internamente, os services também são usáveis diretamente:
    from services.whatsapp_service import get_whatsapp_service
    from services.email_service import get_email_service
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from loguru import logger

from services.whatsapp_service import get_whatsapp_service
from services.email_service import get_email_service
from services.email_templates import list_templates


router = APIRouter(prefix="/messaging")


# =============================================
# MODELS
# =============================================

class WhatsAppTextRequest(BaseModel):
    number: str
    text: str
    delay: int = 1200

class WhatsAppImageRequest(BaseModel):
    number: str
    image_url: str
    caption: str = ""
    delay: int = 1200

class WhatsAppDocumentRequest(BaseModel):
    number: str
    doc_url: str
    filename: str
    caption: str = ""
    delay: int = 1200

class EmailSendRequest(BaseModel):
    to: str
    subject: str
    template_name: str
    variables: dict = {}

class EmailRawRequest(BaseModel):
    to: str
    subject: str
    html_body: str

class TestMessagingRequest(BaseModel):
    whatsapp_number: Optional[str] = None
    email_to: Optional[str] = None


# =============================================
# WHATSAPP ENDPOINTS
# =============================================

@router.post("/whatsapp/send-text")
async def send_whatsapp_text(req: WhatsAppTextRequest):
    """Enviar mensagem de texto via WhatsApp."""
    try:
        svc = get_whatsapp_service()
        result = await svc.send_text(req.number, req.text, req.delay)
        return {"success": True, "result": result}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"[Messaging] WhatsApp text error: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao enviar WhatsApp: {e}")


@router.post("/whatsapp/send-image")
async def send_whatsapp_image(req: WhatsAppImageRequest):
    """Enviar imagem via WhatsApp."""
    try:
        svc = get_whatsapp_service()
        result = await svc.send_image(req.number, req.image_url, req.caption, req.delay)
        return {"success": True, "result": result}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"[Messaging] WhatsApp image error: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao enviar imagem: {e}")


@router.post("/whatsapp/send-document")
async def send_whatsapp_document(req: WhatsAppDocumentRequest):
    """Enviar documento via WhatsApp."""
    try:
        svc = get_whatsapp_service()
        result = await svc.send_document(
            req.number, req.doc_url, req.filename, req.caption, req.delay
        )
        return {"success": True, "result": result}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"[Messaging] WhatsApp document error: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao enviar documento: {e}")


@router.get("/whatsapp/status")
async def whatsapp_status():
    """Verificar status da conexão WhatsApp/UAZAPI."""
    svc = get_whatsapp_service()
    return await svc.check_connection()


# =============================================
# EMAIL ENDPOINTS
# =============================================

@router.post("/email/send")
async def send_email(req: EmailSendRequest):
    """
    Enviar email usando template nomeado.
    
    Templates: welcome, payment_confirmed, subscription_active, password_reset, generic
    """
    try:
        svc = get_email_service()
        result = await svc.send_template(
            to=req.to,
            subject=req.subject,
            template_name=req.template_name,
            **req.variables,
        )
        return {"success": True, "result": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"[Messaging] Email error: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao enviar email: {e}")


@router.post("/email/send-raw")
async def send_email_raw(req: EmailRawRequest):
    """Enviar email com HTML customizado (sem template)."""
    try:
        svc = get_email_service()
        result = await svc.send(to=req.to, subject=req.subject, html_body=req.html_body)
        return {"success": True, "result": result}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"[Messaging] Email raw error: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao enviar email: {e}")


@router.get("/email/templates")
async def email_templates():
    """Listar templates de email disponíveis."""
    return {"templates": list_templates()}


@router.get("/email/status")
async def email_status():
    """Verificar status da conexão SMTP."""
    svc = get_email_service()
    return await svc.check_connection()


# =============================================
# TESTES
# =============================================

@router.post("/test")
async def test_messaging(req: TestMessagingRequest):
    """
    Testar envio de mensagens em ambos os canais.
    Útil para validar configuração.
    """
    results = {}
    
    if req.whatsapp_number:
        try:
            svc = get_whatsapp_service()
            result = await svc.send_text(
                req.whatsapp_number,
                "🧪 *Teste VibraEu*\n\nSe você recebeu esta mensagem, o WhatsApp está configurado corretamente! ✅"
            )
            results["whatsapp"] = {"success": True, "result": result}
        except Exception as e:
            results["whatsapp"] = {"success": False, "error": str(e)}
    
    if req.email_to:
        try:
            svc = get_email_service()
            result = await svc.send_template(
                to=req.email_to,
                subject="🧪 Teste VibraEu — Email configurado!",
                template_name="generic",
                user_name="Administrador",
                title="Teste de Email 🧪",
                body_lines=[
                    "Se você recebeu este email, a configuração SMTP está funcionando corretamente!",
                    "Este é um email de teste enviado pelo sistema VibraEu.",
                ],
                cta_text="Acessar VibraEu",
                cta_url="https://vibraeu.com.br",
            )
            results["email"] = {"success": True, "result": result}
        except Exception as e:
            results["email"] = {"success": False, "error": str(e)}
    
    if not req.whatsapp_number and not req.email_to:
        raise HTTPException(
            status_code=400,
            detail="Informe whatsapp_number e/ou email_to para testar"
        )
    
    return {
        "success": all(r.get("success") for r in results.values()),
        "results": results,
    }
