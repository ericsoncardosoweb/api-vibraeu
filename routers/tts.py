"""
Router para Text-to-Speech (TTS) com OpenAI.
Endpoint genérico para converter texto em áudio MP3.
Usa OpenAI TTS (tts-1) com voz feminina "nova" para pt-BR natural.

Uso: POST /tts/generate
Retorna: Arquivo MP3 como streaming response ou URL do Supabase Storage.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional
from loguru import logger
from io import BytesIO

from config import get_settings

router = APIRouter()

# =============================================
# VOZES DISPONÍVEIS (OpenAI TTS)
# =============================================
# alloy   — neutra, balanceada
# echo    — masculina, grave
# fable   — britânica, narrativa
# onyx    — masculina, profunda
# nova    — feminina, natural, calorosa ★ RECOMENDADA
# shimmer — feminina, suave

VOZES_DISPONIVEIS = ['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer']
VOZ_PADRAO = 'nova'  # Feminina, natural e expressiva

# Modelos
# tts-1    — rápido, qualidade boa (US$15/1M chars)
# tts-1-hd — mais lento, qualidade superior (US$30/1M chars)
MODELO_PADRAO = 'tts-1'

# Limite de caracteres por requisição (OpenAI limita a 4096)
MAX_CHARS = 4096


# =============================================
# MODELS
# =============================================

class TTSRequest(BaseModel):
    """Requisição de geração de áudio TTS."""
    text: str = Field(..., min_length=1, max_length=MAX_CHARS, description="Texto para converter em áudio")
    voice: Optional[str] = Field(default=VOZ_PADRAO, description="Voz: alloy, echo, fable, onyx, nova, shimmer")
    model: Optional[str] = Field(default=MODELO_PADRAO, description="Modelo: tts-1 ou tts-1-hd")
    speed: Optional[float] = Field(default=1.0, ge=0.25, le=4.0, description="Velocidade (0.25-4.0)")
    save_to_storage: Optional[bool] = Field(default=False, description="Salvar no Supabase Storage e retornar URL")
    storage_path: Optional[str] = Field(default=None, description="Path customizado no Storage (ex: mantras/user_id)")
    user_id: Optional[str] = Field(default=None, description="ID do usuário (necessário para save_to_storage)")


class TTSResponse(BaseModel):
    """Resposta com URL do áudio salvo."""
    success: bool
    url: Optional[str] = None
    duration_estimate: Optional[float] = None  # Estimativa em segundos
    chars_processed: int = 0
    error: Optional[str] = None


# =============================================
# FUNÇÕES AUXILIARES
# =============================================

def _strip_html(text: str) -> str:
    """Remove tags HTML para enviar texto limpo ao TTS."""
    import re
    # Remove tags HTML
    clean = re.sub(r'<[^>]+>', ' ', text)
    # Remove múltiplos espaços
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def _get_openai_client():
    """Cria cliente OpenAI."""
    from openai import OpenAI
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key não configurada")
    return OpenAI(api_key=settings.openai_api_key)


async def _save_to_bunny(audio_bytes: bytes, path: str) -> str:
    """Salva o áudio no Bunny CDN e retorna URL pública."""
    from services.bunny_storage import get_bunny_storage
    
    bunny = get_bunny_storage()
    if not bunny:
        raise HTTPException(status_code=503, detail="Serviço de upload (Bunny) não disponível")
    
    # Separar folder e filename do path
    parts = path.rsplit('/', 1)
    if len(parts) == 2:
        folder = f"tts-audio/{parts[0]}"
        filename = parts[1]
    else:
        folder = "tts-audio"
        filename = parts[0]
    
    url = await bunny.upload_file(audio_bytes, folder, filename)
    return url


# =============================================
# ENDPOINTS
# =============================================

@router.post("/generate", response_model=None)
async def generate_tts(request: TTSRequest):
    """
    Gera áudio MP3 a partir de texto usando OpenAI TTS.
    
    Se save_to_storage=False (padrão), retorna streaming MP3 direto.
    Se save_to_storage=True, salva no Supabase Storage e retorna URL.
    
    Vozes recomendadas para pt-BR:
    - nova (feminina, natural, calorosa) ★
    - shimmer (feminina, suave)
    - alloy (neutra)
    """
    
    # Validar voz
    voice = request.voice or VOZ_PADRAO
    if voice not in VOZES_DISPONIVEIS:
        raise HTTPException(status_code=400, detail=f"Voz inválida: '{voice}'. Use: {VOZES_DISPONIVEIS}")
    
    # Limpar HTML do texto
    clean_text = _strip_html(request.text)
    
    if not clean_text or len(clean_text.strip()) < 2:
        raise HTTPException(status_code=400, detail="Texto vazio ou muito curto após limpeza")
    
    # Truncar se necessário
    if len(clean_text) > MAX_CHARS:
        clean_text = clean_text[:MAX_CHARS]
        logger.warning(f"[TTS] Texto truncado para {MAX_CHARS} chars")
    
    try:
        logger.info(f"[TTS] Gerando áudio: {len(clean_text)} chars, voz={voice}, modelo={request.model}")
        
        client = _get_openai_client()
        
        # Gerar áudio
        response = client.audio.speech.create(
            model=request.model or MODELO_PADRAO,
            voice=voice,
            input=clean_text,
            speed=request.speed or 1.0,
            response_format="mp3"
        )
        
        # Ler bytes do áudio
        audio_bytes = response.content
        
        logger.info(f"[TTS] ✅ Áudio gerado: {len(audio_bytes)} bytes ({len(clean_text)} chars)")
        
        # Estimativa de duração (~150 palavras/min em fala normal)
        word_count = len(clean_text.split())
        duration_estimate = round(word_count / 2.5, 1)  # ~2.5 palavras/seg
        
        if request.save_to_storage:
            # Salvar no Supabase Storage e retornar URL
            if not request.user_id:
                raise HTTPException(status_code=400, detail="user_id obrigatório para save_to_storage")
            
            import time
            storage_path = request.storage_path or f"{request.user_id}/tts_{int(time.time())}.mp3"
            
            try:
                url = await _save_to_bunny(audio_bytes, storage_path)
                
                return TTSResponse(
                    success=True,
                    url=url,
                    duration_estimate=duration_estimate,
                    chars_processed=len(clean_text)
                )
            except Exception as storage_err:
                logger.error(f"[TTS] Erro ao salvar no Storage: {storage_err}")
                # Fallback: retorna streaming mesmo
                logger.info("[TTS] Fallback: retornando streaming MP3")
        
        # Retornar como streaming MP3 (sem salvar)
        return StreamingResponse(
            BytesIO(audio_bytes),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=tts_audio.mp3",
                "X-TTS-Duration-Estimate": str(duration_estimate),
                "X-TTS-Chars": str(len(clean_text))
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[TTS] ❌ Erro: {e}")
        
        error_msg = "Erro ao gerar áudio. Tente novamente."
        if "rate_limit" in str(e).lower() or "429" in str(e):
            error_msg = "Limite de requisições excedido. Aguarde um momento."
        elif "invalid_api_key" in str(e).lower():
            error_msg = "Configuração de API inválida."
        
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/voices")
async def list_voices():
    """Lista vozes disponíveis para TTS."""
    return {
        "voices": [
            {"id": "nova", "name": "Nova", "gender": "feminina", "style": "Natural, calorosa", "recommended": True},
            {"id": "shimmer", "name": "Shimmer", "gender": "feminina", "style": "Suave, calma"},
            {"id": "alloy", "name": "Alloy", "gender": "neutra", "style": "Balanceada"},
            {"id": "echo", "name": "Echo", "gender": "masculina", "style": "Grave"},
            {"id": "fable", "name": "Fable", "gender": "neutra", "style": "Narrativa, britânica"},
            {"id": "onyx", "name": "Onyx", "gender": "masculina", "style": "Profunda"},
        ],
        "default_voice": VOZ_PADRAO,
        "models": [
            {"id": "tts-1", "name": "Standard", "description": "Rápido, boa qualidade"},
            {"id": "tts-1-hd", "name": "HD", "description": "Premium, alta fidelidade"},
        ]
    }
