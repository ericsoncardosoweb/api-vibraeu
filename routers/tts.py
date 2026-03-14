"""
Router para Text-to-Speech (TTS) com OpenAI.
Endpoint genérico para converter texto em áudio MP3.
Usa OpenAI TTS (tts-1) com voz feminina "nova" para pt-BR natural.

CACHE: Antes de gerar, verifica a tabela tts_audio_cache no Supabase.
Se o áudio já foi gerado para o mesmo texto+voz, retorna a URL do Bunny CDN direto.
Após gerar um áudio novo, salva no Bunny CDN e registra no banco.

Uso: POST /tts/generate
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from loguru import logger
import hashlib

from config import get_settings

router = APIRouter()

# =============================================
# CONFIGURAÇÃO
# =============================================
VOZES_DISPONIVEIS = ['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer']
VOZ_PADRAO = 'nova'
MODELO_PADRAO = 'tts-1'
MAX_CHARS = 4096


# =============================================
# MODELS
# =============================================

class TTSRequest(BaseModel):
    """Requisição de geração de áudio TTS."""
    text: str = Field(..., min_length=1, max_length=MAX_CHARS)
    voice: Optional[str] = Field(default=VOZ_PADRAO)
    model: Optional[str] = Field(default=MODELO_PADRAO)
    speed: Optional[float] = Field(default=1.0, ge=0.25, le=4.0)
    user_id: Optional[str] = Field(default=None)
    source: Optional[str] = Field(default=None, description="Origem: mantras, anotacoes, jornadas")


class TTSResponse(BaseModel):
    """Resposta com URL do áudio."""
    success: bool
    url: Optional[str] = None
    duration_estimate: Optional[float] = None
    chars_processed: int = 0
    cached: bool = False
    error: Optional[str] = None


# =============================================
# FUNÇÕES AUXILIARES
# =============================================

def _strip_html(text: str) -> str:
    """Remove tags HTML para enviar texto limpo ao TTS."""
    import re
    clean = re.sub(r'<[^>]+>', ' ', text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def _hash_text(text: str) -> str:
    """Gera SHA-256 do texto para cache lookup."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _get_openai_client():
    """Cria cliente OpenAI."""
    from openai import OpenAI
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key não configurada")
    return OpenAI(api_key=settings.openai_api_key)


async def _check_cache(text_hash: str, voice: str) -> Optional[dict]:
    """Verifica se o áudio já existe no cache (Supabase)."""
    try:
        from services.supabase_client import get_supabase_client
        supabase = get_supabase_client()
        
        result = supabase.table('tts_audio_cache') \
            .select('audio_url, duration_estimate') \
            .eq('text_hash', text_hash) \
            .eq('voice', voice) \
            .limit(1) \
            .execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        logger.warning(f"[TTS] Cache check failed (não crítico): {e}")
        return None


async def _save_to_cache(text_hash: str, voice: str, audio_url: str, 
                          text_preview: str, duration: float, chars: int,
                          user_id: str = None, source: str = None):
    """Salva áudio gerado no cache (Supabase)."""
    try:
        from services.supabase_client import get_supabase_client
        supabase = get_supabase_client()
        
        supabase.table('tts_audio_cache').upsert({
            'text_hash': text_hash,
            'voice': voice,
            'audio_url': audio_url,
            'text_preview': text_preview[:200],
            'duration_estimate': duration,
            'chars_count': chars,
            'user_id': user_id,
            'source': source
        }, on_conflict='text_hash,voice').execute()
        
        logger.info(f"[TTS] ✅ Cache salvo: hash={text_hash[:12]}... voice={voice}")
    except Exception as e:
        logger.warning(f"[TTS] Cache save failed (não crítico): {e}")


async def _upload_to_bunny(audio_bytes: bytes, user_id: str, text_hash: str) -> str:
    """Salva o áudio no Bunny CDN e retorna URL."""
    from services.bunny_storage import get_bunny_storage
    import time
    
    bunny = get_bunny_storage()
    if not bunny:
        raise HTTPException(status_code=503, detail="Serviço de upload (Bunny) não disponível")
    
    folder = f"tts-audio/{user_id or 'global'}"
    filename = f"{text_hash[:16]}_{int(time.time())}.mp3"
    
    url = await bunny.upload_file(audio_bytes, folder, filename)
    return url


# =============================================
# ENDPOINTS
# =============================================

@router.post("/generate", response_model=TTSResponse)
async def generate_tts(request: TTSRequest):
    """
    Gera áudio MP3 a partir de texto usando OpenAI TTS.
    
    Fluxo:
    1. Limpa HTML e gera hash do texto
    2. Verifica cache (tts_audio_cache no Supabase)
    3. Se cachado → retorna URL do Bunny CDN (sem custo OpenAI)
    4. Se não → gera via OpenAI → upload Bunny → salva cache → retorna URL
    
    Sempre retorna JSON com URL do áudio.
    """
    
    voice = request.voice or VOZ_PADRAO
    if voice not in VOZES_DISPONIVEIS:
        raise HTTPException(status_code=400, detail=f"Voz inválida: '{voice}'")
    
    # Limpar HTML
    clean_text = _strip_html(request.text)
    if not clean_text or len(clean_text.strip()) < 2:
        raise HTTPException(status_code=400, detail="Texto vazio ou muito curto")
    
    if len(clean_text) > MAX_CHARS:
        clean_text = clean_text[:MAX_CHARS]
    
    # Hash para cache
    text_hash = _hash_text(clean_text)
    
    # ── Step 1: Verificar cache ──
    cached = await _check_cache(text_hash, voice)
    if cached:
        logger.info(f"[TTS] 🎯 Cache HIT: hash={text_hash[:12]}... → {cached['audio_url'][:50]}...")
        return TTSResponse(
            success=True,
            url=cached['audio_url'],
            duration_estimate=cached.get('duration_estimate', 0),
            chars_processed=len(clean_text),
            cached=True
        )
    
    # ── Step 2: Gerar áudio via OpenAI ──
    try:
        logger.info(f"[TTS] 🔄 Cache MISS — gerando: {len(clean_text)} chars, voz={voice}")
        
        client = _get_openai_client()
        
        response = client.audio.speech.create(
            model=request.model or MODELO_PADRAO,
            voice=voice,
            input=clean_text,
            speed=request.speed or 1.0,
            response_format="mp3"
        )
        
        audio_bytes = response.content
        
        # Estimativa de duração
        word_count = len(clean_text.split())
        duration_estimate = round(word_count / 2.5, 1)
        
        logger.info(f"[TTS] ✅ Áudio gerado: {len(audio_bytes)} bytes, ~{duration_estimate}s")
        
        # ── Step 3: Upload para Bunny CDN ──
        audio_url = await _upload_to_bunny(audio_bytes, request.user_id, text_hash)
        
        # ── Step 4: Salvar no cache (Supabase) ──
        await _save_to_cache(
            text_hash=text_hash,
            voice=voice,
            audio_url=audio_url,
            text_preview=clean_text,
            duration=duration_estimate,
            chars=len(clean_text),
            user_id=request.user_id,
            source=request.source
        )
        
        return TTSResponse(
            success=True,
            url=audio_url,
            duration_estimate=duration_estimate,
            chars_processed=len(clean_text),
            cached=False
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
