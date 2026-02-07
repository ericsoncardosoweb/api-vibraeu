"""
Email Service — Serviço centralizado de envio de emails via SMTP.
Reutilizável por: routers, scheduler, AIMS engine, cron jobs

Usa aiosmtplib para envio assíncrono.
Templates HTML estão em email_templates.py.
"""

import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from typing import Optional
from loguru import logger

from config import get_settings
from services.email_templates import (
    get_template,
    list_templates as list_template_names,
    generic_template,
)


class EmailService:
    """
    Serviço centralizado de Email via SMTP.
    
    Uso direto (services/scheduler):
        svc = EmailService()
        await svc.send_template("user@email.com", "Bem-vindo!", "welcome", user_name="João")
    
    Uso via router (HTTP):
        POST /messaging/email/send
    """
    
    def __init__(self):
        settings = get_settings()
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.user = settings.smtp_user
        self.password = settings.smtp_password
        self.from_name = settings.smtp_from_name
        self.from_email = settings.smtp_from_email or settings.smtp_user
        self._configured = bool(self.host and self.user and self.password)
    
    @property
    def is_configured(self) -> bool:
        return self._configured
    
    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        reply_to: Optional[str] = None,
    ) -> dict:
        """
        Enviar email HTML.
        
        Args:
            to: Email do destinatário
            subject: Assunto
            html_body: Corpo HTML completo
            reply_to: Email de resposta (opcional)
        
        Returns:
            dict com status do envio
        """
        if not self._configured:
            raise RuntimeError(
                "Email SMTP não configurado. Verifique SMTP_HOST, SMTP_USER e SMTP_PASSWORD no .env"
            )
        
        msg = MIMEMultipart("alternative")
        msg["From"] = formataddr((self.from_name, self.from_email))
        msg["To"] = to
        msg["Subject"] = subject
        
        if reply_to:
            msg["Reply-To"] = reply_to
        
        # HTML part
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        
        try:
            logger.info(f"[Email] Enviando para {to} — '{subject}'")
            
            await aiosmtplib.send(
                msg,
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                use_tls=False,
                start_tls=True,
            )
            
            logger.info(f"[Email] ✅ Enviado para {to}")
            return {"success": True, "to": to, "subject": subject}
            
        except aiosmtplib.SMTPAuthenticationError as e:
            logger.error(f"[Email] ❌ Erro de autenticação SMTP: {e}")
            raise RuntimeError(f"Erro de autenticação SMTP: {e}")
        except Exception as e:
            logger.error(f"[Email] ❌ Erro ao enviar: {e}")
            raise RuntimeError(f"Erro ao enviar email: {e}")
    
    async def send_template(
        self,
        to: str,
        subject: str,
        template_name: str,
        **variables,
    ) -> dict:
        """
        Enviar email usando um template nomeado.
        
        Args:
            to: Email do destinatário
            subject: Assunto
            template_name: Nome do template (welcome, payment_confirmed, etc.)
            **variables: Variáveis do template (user_name, plan_name, etc.)
        
        Templates disponíveis:
            - welcome(user_name)
            - payment_confirmed(user_name, plan_name, value)
            - subscription_active(user_name, plan_name)
            - password_reset(user_name, reset_url)
            - generic(user_name, title, body_lines, cta_text, cta_url)
        """
        template_fn = get_template(template_name)
        if not template_fn:
            available = list_template_names()
            raise ValueError(
                f"Template '{template_name}' não encontrado. "
                f"Disponíveis: {', '.join(available)}"
            )
        
        html_body = template_fn(**variables)
        return await self.send(to, subject, html_body)
    
    async def send_transactional(
        self,
        to: str,
        subject: str,
        title: str,
        body_lines: list[str],
        cta_text: str = None,
        cta_url: str = None,
        user_name: str = "Usuário",
    ) -> dict:
        """
        Atalho para enviar email transacional genérico com template VibraEu.
        
        Args:
            to: Email do destinatário
            subject: Assunto
            title: Título no corpo do email
            body_lines: Lista de parágrafos HTML
            cta_text: Texto do botão CTA (opcional)
            cta_url: URL do botão (opcional)
            user_name: Nome do usuário
        """
        html_body = generic_template(
            user_name=user_name,
            title=title,
            body_lines=body_lines,
            cta_text=cta_text,
            cta_url=cta_url,
        )
        return await self.send(to, subject, html_body)
    
    async def check_connection(self) -> dict:
        """Verificar se a conexão SMTP está funcional."""
        if not self._configured:
            return {"connected": False, "error": "Não configurado"}
        
        try:
            smtp = aiosmtplib.SMTP(
                hostname=self.host,
                port=self.port,
                use_tls=False,
                start_tls=True,
            )
            await smtp.connect()
            await smtp.login(self.user, self.password)
            await smtp.quit()
            
            return {
                "connected": True,
                "host": self.host,
                "from": self.from_email,
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}


# Singleton para uso rápido
_email_instance = None


def get_email_service() -> EmailService:
    """Retorna instância singleton do EmailService."""
    global _email_instance
    if _email_instance is None:
        _email_instance = EmailService()
    return _email_instance
