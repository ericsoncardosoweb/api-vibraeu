"""
WhatsApp Service — Integração centralizada com UAZAPI
Reutilizável por: routers, scheduler, AIMS engine, cron jobs

Endpoints UAZAPI:
  POST /message/sendText   → Texto
  POST /message/sendMedia  → Imagem, documento, áudio
  GET  /instance/status    → Status da conexão
"""

import httpx
from typing import Optional, Dict, Any
from loguru import logger

from config import get_settings


class WhatsAppService:
    """
    Serviço centralizado de WhatsApp via UAZAPI.
    
    Uso direto (services/scheduler):
        svc = WhatsAppService()
        await svc.send_text("5516991708301", "Olá!")
    
    Uso via router (HTTP):
        POST /messaging/whatsapp/send-text
    """
    
    def __init__(self):
        settings = get_settings()
        self.server_url = settings.uazapi_server_url.rstrip("/")
        self.token = settings.uazapi_instance_token
        self.default_number = settings.uazapi_default_number
        self._configured = bool(self.server_url and self.token)
    
    @property
    def is_configured(self) -> bool:
        return self._configured
    
    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "token": self.token,
        }
    
    async def _request(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Request interno para UAZAPI."""
        if not self._configured:
            raise RuntimeError("WhatsApp (UAZAPI) não configurado. Verifique UAZAPI_SERVER_URL e UAZAPI_INSTANCE_TOKEN no .env")
        
        url = f"{self.server_url}{endpoint}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "GET":
                resp = await client.get(url, headers=self._headers())
            else:
                resp = await client.post(url, headers=self._headers(), json=data)
        
        if not resp.is_success:
            logger.error(f"[WhatsApp] {method} {endpoint} → {resp.status_code}: {resp.text}")
            raise RuntimeError(f"Erro UAZAPI ({resp.status_code}): {resp.text}")
        
        return resp.json()
    
    def _format_number(self, number: str) -> str:
        """Normaliza número: remove formatação, mantém código do país."""
        clean = number.replace(" ", "").replace("-", "").replace("(", "").replace(")", "").replace("+", "")
        # Se não tem código do país, adiciona 55 (Brasil)
        if len(clean) <= 11:
            clean = f"55{clean}"
        return clean
    
    # =============================================
    # ENVIO DE MENSAGENS
    # =============================================
    
    async def send_text(
        self,
        number: str,
        text: str,
        delay: int = 1200,
        link_preview: bool = True,
    ) -> dict:
        """
        Enviar mensagem de texto.
        
        Args:
            number: Número do destinatário (ex: "5516991708301")
            text: Texto da mensagem
            delay: Delay em ms (mostra "Digitando..." no WhatsApp)
            link_preview: Mostrar preview de links
        """
        payload = {
            "number": self._format_number(number),
            "text": text,
            "delay": delay,
            "linkPreview": link_preview,
        }
        
        logger.info(f"[WhatsApp] Enviando texto para {number[:8]}***")
        result = await self._request("POST", "/message/sendText", payload)
        logger.info(f"[WhatsApp] ✅ Texto enviado")
        return result
    
    async def send_image(
        self,
        number: str,
        image_url: str,
        caption: str = "",
        delay: int = 1200,
    ) -> dict:
        """
        Enviar imagem por URL.
        
        Args:
            number: Número do destinatário
            image_url: URL pública da imagem
            caption: Legenda (opcional)
        """
        payload = {
            "number": self._format_number(number),
            "media": image_url,
            "mediatype": "image",
            "caption": caption,
            "delay": delay,
        }
        
        logger.info(f"[WhatsApp] Enviando imagem para {number[:8]}***")
        result = await self._request("POST", "/message/sendMedia", payload)
        logger.info(f"[WhatsApp] ✅ Imagem enviada")
        return result
    
    async def send_document(
        self,
        number: str,
        doc_url: str,
        filename: str,
        caption: str = "",
        delay: int = 1200,
    ) -> dict:
        """
        Enviar documento por URL.
        
        Args:
            number: Número do destinatário
            doc_url: URL pública do documento
            filename: Nome do arquivo (ex: "relatorio.pdf")
        """
        payload = {
            "number": self._format_number(number),
            "media": doc_url,
            "mediatype": "document",
            "caption": caption,
            "fileName": filename,
            "delay": delay,
        }
        
        logger.info(f"[WhatsApp] Enviando doc '{filename}' para {number[:8]}***")
        result = await self._request("POST", "/message/sendMedia", payload)
        logger.info(f"[WhatsApp] ✅ Documento enviado")
        return result
    
    async def send_audio(
        self,
        number: str,
        audio_url: str,
        delay: int = 1200,
    ) -> dict:
        """Enviar áudio por URL."""
        payload = {
            "number": self._format_number(number),
            "media": audio_url,
            "mediatype": "audio",
            "delay": delay,
        }
        
        logger.info(f"[WhatsApp] Enviando áudio para {number[:8]}***")
        result = await self._request("POST", "/message/sendMedia", payload)
        logger.info(f"[WhatsApp] ✅ Áudio enviado")
        return result
    
    # =============================================
    # STATUS / UTILITÁRIOS
    # =============================================
    
    async def check_connection(self) -> dict:
        """Verificar status da conexão UAZAPI."""
        if not self._configured:
            return {"connected": False, "error": "Não configurado"}
        
        try:
            result = await self._request("GET", "/instance/status")
            return {
                "connected": True,
                "status": result,
                "number": self.default_number,
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}
    
    # =============================================
    # TEMPLATES DE MENSAGEM
    # =============================================
    
    async def send_welcome(self, number: str, user_name: str) -> dict:
        """Template: Boas-vindas ao VibraEu."""
        text = (
            f"🌟 *Olá, {user_name}!*\n\n"
            "Bem-vindo(a) ao *VibraEu*! 🎉\n\n"
            "Aqui você vai descobrir sua essência através da Astrologia Cabalística "
            "e acompanhar sua evolução pessoal.\n\n"
            "✨ Comece gerando seu *Mapa Astral Cabalístico (MAC)* no app!\n\n"
            "Qualquer dúvida, estamos por aqui. 💜"
        )
        return await self.send_text(number, text)
    
    async def send_payment_confirmed(self, number: str, user_name: str, plan: str, value: str) -> dict:
        """Template: Pagamento confirmado."""
        text = (
            f"✅ *Pagamento Confirmado!*\n\n"
            f"Olá, {user_name}!\n\n"
            f"Seu plano *{plan}* no valor de *{value}* foi confirmado com sucesso.\n\n"
            "🚀 Todos os recursos do seu plano já estão disponíveis!\n\n"
            "Acesse: https://vibraeu.com.br/inicio"
        )
        return await self.send_text(number, text)
    
    async def send_notification(self, number: str, title: str, message: str) -> dict:
        """Template: Notificação genérica."""
        text = f"🔔 *{title}*\n\n{message}"
        return await self.send_text(number, text)


# Singleton para uso rápido
_whatsapp_instance = None

def get_whatsapp_service() -> WhatsAppService:
    """Retorna instância singleton do WhatsAppService."""
    global _whatsapp_instance
    if _whatsapp_instance is None:
        _whatsapp_instance = WhatsAppService()
    return _whatsapp_instance
