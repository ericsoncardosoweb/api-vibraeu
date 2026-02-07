"""
Email Templates — HTML premium com identidade visual VibraEu.
Templates inline-CSS para máxima compatibilidade com clientes de email.
"""


# =============================================
# CONSTANTES VISUAIS
# =============================================

LOGO_URL = "https://vibraeu.com.br/logo-vibraeu.svg"
BRAND_PRIMARY = "#9933CC"
BRAND_SECONDARY = "#00CCD6"
BRAND_GRADIENT = "linear-gradient(135deg, #9933CC 0%, #00CCD6 100%)"
BRAND_BG_DARK = "#1a1a2e"
BRAND_BG_CARD = "#16213e"
BRAND_TEXT = "#e0e0e0"
BRAND_TEXT_MUTED = "#a0a0b0"
BRAND_ACCENT = "#bb86fc"

FONT_STACK = "'Inter', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
APP_URL = "https://vibraeu.com.br"


# =============================================
# BASE TEMPLATE
# =============================================

def _base_template(content: str, preheader: str = "") -> str:
    """Wrapper HTML base com header/footer VibraEu."""
    return f"""<!DOCTYPE html>
<html lang="pt-BR" xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>VibraEu</title>
    <!--[if mso]>
    <style type="text/css">
        body, table, td {{font-family: Arial, Helvetica, sans-serif !important;}}
    </style>
    <![endif]-->
</head>
<body style="margin:0; padding:0; background-color:#0f0f23; font-family:{FONT_STACK}; -webkit-font-smoothing:antialiased;">
    {f'<div style="display:none;max-height:0;overflow:hidden;">{preheader}</div>' if preheader else ''}
    
    <!-- Container -->
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#0f0f23;">
        <tr>
            <td align="center" style="padding:24px 16px;">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px; width:100%;">
                    
                    <!-- HEADER -->
                    <tr>
                        <td style="
                            background: {BRAND_GRADIENT};
                            border-radius: 16px 16px 0 0;
                            padding: 32px 40px;
                            text-align: center;
                        ">
                            <img src="{LOGO_URL}" alt="VibraEu" width="140" style="
                                display: inline-block;
                                max-width: 140px;
                                height: auto;
                                filter: brightness(10);
                            " onerror="this.style.display='none'">
                            <div style="
                                margin-top: 8px;
                                font-size: 28px;
                                font-weight: 700;
                                color: #ffffff;
                                letter-spacing: 1px;
                            ">VibraEu</div>
                            <div style="
                                margin-top: 4px;
                                font-size: 13px;
                                color: rgba(255,255,255,0.8);
                                letter-spacing: 0.5px;
                            ">Astrologia Cabalística & Autoconhecimento</div>
                        </td>
                    </tr>
                    
                    <!-- CONTENT -->
                    <tr>
                        <td style="
                            background-color: {BRAND_BG_DARK};
                            padding: 40px;
                            border-left: 1px solid rgba(153,51,204,0.2);
                            border-right: 1px solid rgba(0,204,214,0.2);
                        ">
                            {content}
                        </td>
                    </tr>
                    
                    <!-- FOOTER -->
                    <tr>
                        <td style="
                            background-color: {BRAND_BG_CARD};
                            border-radius: 0 0 16px 16px;
                            padding: 24px 40px;
                            text-align: center;
                            border-top: 1px solid rgba(153,51,204,0.3);
                        ">
                            <div style="margin-bottom: 16px;">
                                <a href="{APP_URL}" style="color:{BRAND_ACCENT}; text-decoration:none; font-size:13px; margin:0 8px;">🌐 Site</a>
                                <a href="{APP_URL}/inicio" style="color:{BRAND_ACCENT}; text-decoration:none; font-size:13px; margin:0 8px;">📱 App</a>
                                <a href="{APP_URL}/comunidade" style="color:{BRAND_ACCENT}; text-decoration:none; font-size:13px; margin:0 8px;">👥 Comunidade</a>
                            </div>
                            <div style="color:{BRAND_TEXT_MUTED}; font-size:11px; line-height:1.6;">
                                © 2026 VibraEu — Todos os direitos reservados.<br>
                                <a href="{APP_URL}/termos" style="color:{BRAND_TEXT_MUTED}; text-decoration:underline;">Termos de Uso</a> · 
                                <a href="{APP_URL}/privacidade" style="color:{BRAND_TEXT_MUTED}; text-decoration:underline;">Privacidade</a>
                            </div>
                        </td>
                    </tr>
                    
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""


# =============================================
# COMPONENTES REUTILIZÁVEIS
# =============================================

def _heading(text: str) -> str:
    return f'<h1 style="color:#ffffff; font-size:24px; font-weight:700; margin:0 0 16px 0; line-height:1.3;">{text}</h1>'


def _subheading(text: str) -> str:
    return f'<h2 style="color:{BRAND_ACCENT}; font-size:18px; font-weight:600; margin:0 0 12px 0;">{text}</h2>'


def _paragraph(text: str) -> str:
    return f'<p style="color:{BRAND_TEXT}; font-size:15px; line-height:1.7; margin:0 0 16px 0;">{text}</p>'


def _cta_button(text: str, url: str) -> str:
    return f'''<table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px auto;">
        <tr>
            <td style="
                background: {BRAND_GRADIENT};
                border-radius: 12px;
                text-align: center;
            ">
                <a href="{url}" target="_blank" style="
                    display: inline-block;
                    padding: 14px 36px;
                    color: #ffffff;
                    font-size: 15px;
                    font-weight: 600;
                    text-decoration: none;
                    letter-spacing: 0.5px;
                ">{text}</a>
            </td>
        </tr>
    </table>'''


def _divider() -> str:
    return f'<hr style="border:none; border-top:1px solid rgba(153,51,204,0.2); margin:24px 0;">'


def _info_box(text: str, icon: str = "ℹ️") -> str:
    return f'''<div style="
        background-color: rgba(153,51,204,0.1);
        border-left: 3px solid {BRAND_PRIMARY};
        border-radius: 0 8px 8px 0;
        padding: 16px 20px;
        margin: 16px 0;
    ">
        <span style="font-size:18px;">{icon}</span>
        <span style="color:{BRAND_TEXT}; font-size:14px; margin-left:8px;">{text}</span>
    </div>'''


# =============================================
# TEMPLATES PRONTOS
# =============================================

def welcome_template(user_name: str) -> str:
    """Template: Boas-vindas ao VibraEu."""
    content = f"""
        {_heading(f"Bem-vindo(a), {user_name}! 🌟")}
        {_paragraph("É uma alegria ter você no <strong>VibraEu</strong>! Aqui você vai descobrir sua essência através da <strong>Astrologia Cabalística</strong> e acompanhar sua evolução pessoal.")}
        {_divider()}
        {_subheading("Seus primeiros passos:")}
        {_paragraph("1️⃣ <strong>Gere seu MAC</strong> — Mapa Astral Cabalístico<br>2️⃣ <strong>Complete seu perfil</strong> — Para personalizar sua experiência<br>3️⃣ <strong>Explore as vibrações</strong> — Acompanhe seu dia, semana e mês")}
        {_cta_button("Começar agora ✨", f"{APP_URL}/onboard")}
        {_info_box("Dica: Complete todas as etapas do onboarding para desbloquear todos os recursos!")}
    """
    return _base_template(content, preheader=f"Bem-vindo(a) ao VibraEu, {user_name}!")


def payment_confirmed_template(user_name: str, plan_name: str, value: str) -> str:
    """Template: Pagamento confirmado."""
    content = f"""
        {_heading("Pagamento Confirmado! ✅")}
        {_paragraph(f"Olá, <strong>{user_name}</strong>!")}
        {_paragraph(f"Seu plano <strong>{plan_name}</strong> no valor de <strong>{value}</strong> foi confirmado com sucesso.")}
        {_divider()}
        {_info_box("🚀 Todos os recursos do seu plano já estão disponíveis!")}
        {_cta_button("Acessar minha conta", f"{APP_URL}/inicio")}
        {_paragraph('<span style="color:#a0a0b0; font-size:13px;">Se você não reconhece esta transação, entre em contato conosco.</span>')}
    """
    return _base_template(content, preheader=f"Pagamento de {value} confirmado — {plan_name}")


def subscription_active_template(user_name: str, plan_name: str) -> str:
    """Template: Assinatura ativada."""
    content = f"""
        {_heading("Assinatura Ativa! 🎉")}
        {_paragraph(f"Parabéns, <strong>{user_name}</strong>!")}
        {_paragraph(f"Sua assinatura <strong>{plan_name}</strong> está ativa e todos os recursos estão liberados.")}
        {_divider()}
        {_subheading("O que você ganhou:")}
        {_paragraph("✨ Interpretações avançadas do seu MAC<br>🔮 Chat com Luna (sua assistente astrológica)<br>💫 Centelhas mensais para explorações profundas<br>📊 Relatórios exclusivos de compatibilidade")}
        {_cta_button("Explorar recursos ✨", f"{APP_URL}/inicio")}
    """
    return _base_template(content, preheader=f"Sua assinatura {plan_name} está ativa!")


def generic_template(
    user_name: str,
    title: str,
    body_lines: list[str],
    cta_text: str = None,
    cta_url: str = None,
) -> str:
    """
    Template genérico reutilizável.
    
    Args:
        user_name: Nome do usuário
        title: Título principal
        body_lines: Lista de parágrafos
        cta_text: Texto do botão (opcional)
        cta_url: URL do botão (opcional)
    """
    body = "".join(_paragraph(line) for line in body_lines)
    cta = _cta_button(cta_text, cta_url) if cta_text and cta_url else ""
    
    content = f"""
        {_heading(title)}
        {_paragraph(f"Olá, <strong>{user_name}</strong>!")}
        {_divider()}
        {body}
        {cta}
    """
    return _base_template(content, preheader=title)


def password_reset_template(user_name: str, reset_url: str) -> str:
    """Template: Reset de senha."""
    content = f"""
        {_heading("Redefinir Senha 🔒")}
        {_paragraph(f"Olá, <strong>{user_name}</strong>!")}
        {_paragraph("Recebemos uma solicitação para redefinir sua senha. Clique no botão abaixo:")}
        {_cta_button("Redefinir minha senha", reset_url)}
        {_info_box("⚠️ Se você não solicitou esta alteração, apenas ignore este email.", "⚠️")}
        {_paragraph(f'<span style="color:#a0a0b0; font-size:12px;">Este link expira em 1 hora.</span>')}
    """
    return _base_template(content, preheader=f"Redefinição de senha — VibraEu")


# =============================================
# MAPA DE TEMPLATES
# =============================================

TEMPLATES = {
    "welcome": welcome_template,
    "payment_confirmed": payment_confirmed_template,
    "subscription_active": subscription_active_template,
    "generic": generic_template,
    "password_reset": password_reset_template,
}


def get_template(name: str):
    """Retorna função de template por nome."""
    return TEMPLATES.get(name)


def list_templates() -> list[str]:
    """Lista nomes de templates disponíveis."""
    return list(TEMPLATES.keys())
