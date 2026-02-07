"""
Configuration settings for the Advanced Interpretation System.
Loads environment variables and provides typed settings.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # App Info
    app_name: str = "VibraEU API"
    app_version: str = "2.0.0"
    debug: bool = False
    
    # Security
    api_key: Optional[str] = None  # Se configurada, protege rotas com X-API-Key
    
    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = ""
    
    # LLM Providers
    openai_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    
    # Default LLM Config
    default_provider: str = "groq"
    default_model: str = "llama-3.3-70b-versatile"
    fallback_provider: str = "openai"
    fallback_model: str = "gpt-4.1-mini"
    
    # Scheduler
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 60
    
    # Processing
    max_retries: int = 3
    processing_timeout_seconds: int = 120
    batch_size: int = 10
    
    # CORS
    cors_origins: str = "*"
    
    # Bunny Storage
    bunny_enabled: bool = False
    bunny_storage_zone: Optional[str] = None
    bunny_storage_api_key: Optional[str] = None
    bunny_storage_hostname: Optional[str] = None
    bunny_cdn_url: Optional[str] = None
    
    # Asaas Payment Gateway
    asaas_environment: str = "sandbox"  # "sandbox" ou "production"
    asaas_prod_api_key: Optional[str] = None
    asaas_sandbox_api_key: Optional[str] = None
    
    # WhatsApp (UAZAPI)
    uazapi_server_url: str = ""
    uazapi_instance_token: str = ""
    uazapi_default_number: str = ""
    
    # Email (SMTP)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_name: str = "VibraEu"
    smtp_from_email: str = ""
    
    # Astrology / Pastas locais
    pasta_imagens: str = "mapas_gerados"
    pasta_avatars: str = "avatars"
    api_base_url: str = "https://api.vibraeu.com.br"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Ignora variáveis extras (como VITE_* do frontend)


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
