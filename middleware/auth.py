"""
Middleware de autenticação e segurança.
"""

from fastapi import HTTPException, Security, Depends, Request
from fastapi.security import APIKeyHeader
from loguru import logger
from config import get_settings

# Header para API Key
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    request: Request,
    api_key: str = Security(api_key_header)
):
    """
    Verifica a API key no header X-API-Key.
    Rotas públicas (health, docs) são isentas.
    
    Se API_KEY não estiver configurada no .env, todas as rotas
    ficam abertas (modo desenvolvimento).
    """
    settings = get_settings()
    
    # Se não tem API key configurada, funciona sem proteção (dev mode)
    if not settings.api_key:
        return None
    
    # Rotas públicas que não precisam de key
    public_paths = ["/health", "/docs", "/openapi.json", "/redoc", "/"]
    if request.url.path in public_paths:
        return None
    
    # Verificar API key
    if not api_key:
        logger.warning(f"Requisição sem API key: {request.method} {request.url.path}")
        raise HTTPException(
            status_code=401,
            detail="API key não fornecida. Use o header X-API-Key."
        )
    
    if api_key != settings.api_key:
        logger.warning(f"API key inválida: {request.method} {request.url.path}")
        raise HTTPException(
            status_code=403,
            detail="API key inválida."
        )
    
    return api_key


async def verify_master_role(api_key: str = Depends(verify_api_key)):
    """
    Verifica permissão de admin/master.
    Por enquanto, qualquer API key válida tem acesso admin.
    Futuramente pode ser expandido com JWT + roles.
    """
    return True
