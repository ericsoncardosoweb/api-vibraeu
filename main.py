"""
VibraEU API — Consolidada
FastAPI application entry point.
Endpoint único: api.vibraeu.com.br
"""

from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from contextlib import asynccontextmanager
from loguru import logger
import sys
import os
import time

from config import get_settings
from routers import trigger, process, scheduler, health, upload, admin
from routers import astrology
from routers import logs
from routers import payments
from routers import messaging
from routers import interpretations
from routers import plans
from routers import users
from routers import notifications
from routers import frases
from scheduler.jobs import start_scheduler, shutdown_scheduler
from middleware.auth import verify_api_key


# Configure loguru
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    level="INFO"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    from services.llm_gateway import close_http_client
    
    settings = get_settings()
    app.state.start_time = time.time()
    
    # Criar pastas locais se não existem
    os.makedirs(settings.pasta_imagens, exist_ok=True)
    os.makedirs(settings.pasta_avatars, exist_ok=True)
    
    logger.info(f"🚀 Starting {settings.app_name} v{settings.app_version}")
    logger.info("⚡ Performance: GZip + HTTP Pool + TTL Cache ENABLED")
    
    if settings.api_key:
        logger.info("🔒 API Key protection ENABLED")
    else:
        logger.warning("⚠️  API Key NOT configured — rotas abertas (modo dev)")
    
    # Start scheduler if enabled
    if settings.scheduler_enabled:
        start_scheduler()
        logger.info("⏰ Scheduler started")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down...")
    await close_http_client()
    shutdown_scheduler()


# Create FastAPI app
app = FastAPI(
    title="VibraEU API",
    description="API unificada — Astrologia, AIMS Interpretações, Uploads",
    version="2.0.0",
    lifespan=lifespan
)

# CORS Middleware
settings = get_settings()
if settings.cors_origins == "*":
    # Wildcard + credentials é proibido pelo browser — listar explicitamente
    origins = [
        "https://admin.vibraeu.com.br",
        "https://vibraeu.com.br",
        "https://www.vibraeu.com.br",
        "https://app.vibraeu.com.br",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3333",
        "http://localhost:3000",
    ]
else:
    origins = [o.strip() for o in settings.cors_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip — comprime respostas > 500 bytes
app.add_middleware(GZipMiddleware, minimum_size=500)

# ============================================================================
# Montar pastas estáticas (para fallback local de imagens/avatars)
# ============================================================================
os.makedirs("mapas_gerados", exist_ok=True)
os.makedirs("avatars", exist_ok=True)

app.mount("/imagens", StaticFiles(directory="mapas_gerados"), name="imagens")
app.mount("/avatars", StaticFiles(directory="avatars"), name="avatars")

# ============================================================================
# Rotas de Astrologia (preservadas do monolito original)
# Protegidas por API key quando configurada
# ============================================================================
app.include_router(
    astrology.router, 
    tags=["Astrologia"],
    dependencies=[Depends(verify_api_key)]
)

# ============================================================================
# Rotas do AIMS (interpretações avançadas)
# ============================================================================
app.include_router(health.router, tags=["Health"])
app.include_router(
    upload.router, 
    tags=["Upload"],
    dependencies=[Depends(verify_api_key)]
)
app.include_router(
    admin.router, 
    prefix="/admin", 
    tags=["Admin"],
    dependencies=[Depends(verify_api_key)]
)
app.include_router(
    trigger.router, 
    prefix="/trigger", 
    tags=["Trigger"],
    dependencies=[Depends(verify_api_key)]
)
app.include_router(
    process.router, 
    prefix="/process", 
    tags=["Process"],
    dependencies=[Depends(verify_api_key)]
)
app.include_router(
    scheduler.router, 
    prefix="/scheduler", 
    tags=["Scheduler"],
    dependencies=[Depends(verify_api_key)]
)

# ============================================================================
# Rotas de Logs (error logging do frontend)
# POST /logs/error é público (frontend precisa logar sem auth)
# GET/PATCH protegidos por API key
# ============================================================================
app.include_router(
    logs.router, 
    tags=["Logs"]
)

# ============================================================================
# Rotas de Pagamento (Asaas) - protegidas por API key
# Frontend chama via apiClient que inclui X-API-Key automaticamente
# ============================================================================
app.include_router(
    payments.router, 
    tags=["Payments"],
    dependencies=[Depends(verify_api_key)]
)

# ============================================================================
# Rotas de Mensageria (WhatsApp + Email)
# Protegidas por API key
# ============================================================================
app.include_router(
    messaging.router, 
    tags=["Messaging"],
    dependencies=[Depends(verify_api_key)]
)

# ============================================================================
# Rotas de Interpretações Globais (geração via IA)
# Protegidas por API key
# ============================================================================
app.include_router(
    interpretations.router, 
    prefix="/admin",
    tags=["Interpretações Globais"],
    dependencies=[Depends(verify_api_key)]
)

# ============================================================================
# Rotas de Planos — Endpoint público (sem auth)
# ============================================================================
app.include_router(
    plans.router, 
    tags=["Plans Config"]
)

# ============================================================================
# Rotas Admin de Planos — CRUD protegido por API key  
# ============================================================================
app.include_router(
    plans.router, 
    prefix="/admin",
    tags=["Plans Admin"],
    dependencies=[Depends(verify_api_key)]
)

# ============================================================================
# Rotas Admin de Users — Gestão de assinantes protegido por API key  
# ============================================================================
app.include_router(
    users.router, 
    prefix="/admin",
    tags=["Users Admin"],
    dependencies=[Depends(verify_api_key)]
)

# ============================================================================
# Rotas Admin de Notificações — Otimização IA + envio dual WhatsApp/Email  
# ============================================================================
app.include_router(
    notifications.router, 
    prefix="/admin",
    tags=["Notifications Admin"],
    dependencies=[Depends(verify_api_key)]
)

# ============================================================================
# Rotas Admin de Frases — CRUD + geração IA, protegido por API key  
# ============================================================================
app.include_router(
    frases.router, 
    prefix="/admin",
    tags=["Frases Admin"],
    dependencies=[Depends(verify_api_key)]
)


@app.get("/")
async def root():
    """Root endpoint with API info."""
    settings = get_settings()
    return {
        "status": "online",
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "rotas": [
            "/natal-ll",
            "/natal-osm", 
            "/hoje",
            "/upload-avatar",
            "/limpar-dados",
            "/admin/trigger-event",
            "/admin/process-queue",
            "/trigger",
            "/process/now",
            "/health",
            "/logs/errors",
            "/payments/*",
            "/plans/config",
            "/admin/plans/*",
            "/admin/users/*"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
