"""
Upload router for avatar and file uploads via Bunny Storage.
"""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Optional
from loguru import logger
import uuid

from services.bunny_storage import get_bunny_storage


router = APIRouter()


@router.post("/upload-avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user_id: str = Form(...)
):
    """
    Upload user avatar to Bunny Storage.
    
    Args:
        file: Image file
        user_id: User UUID
        
    Returns:
        JSON with CDN URL
    """
    try:
        # Validate file type
        if not file.content_type or not file.content_type.startswith('image/'):
            raise HTTPException(
                status_code=400,
                detail="File must be an image"
            )
        
        # Validate user_id format
        try:
            uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid user_id format"
            )
        
        # Get Bunny service
        bunny = get_bunny_storage()
        if not bunny:
            raise HTTPException(
                status_code=503,
                detail="Upload service not available"
            )
        
        # Read file content
        file_content = await file.read()
        
        # Validate file size (max 5MB)
        if len(file_content) > 5 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail="File size must be less than 5MB"
            )
        
        # Get file extension
        filename = file.filename or "image.jpg"
        ext = filename.split('.')[-1].lower()
        
        # Allowed extensions
        allowed_exts = ['jpg', 'jpeg', 'png', 'gif', 'webp']
        if ext not in allowed_exts:
            raise HTTPException(
                status_code=400,
                detail=f"File type not allowed. Use: {', '.join(allowed_exts)}"
            )
        
        # Upload to Bunny
        url = await bunny.upload_avatar(file_content, user_id, ext)
        
        logger.info(f"Avatar uploaded for user {user_id}: {url}")
        
        return {
            "success":True,
            "url": url,
            "message": "Avatar uploaded successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Upload failed: {str(e)}"
        )


@router.get("/upload/status")
async def upload_status():
    """
    Check if upload service is available.
    """
    bunny = get_bunny_storage()
    
    return {
        "available": bunny is not None,
        "provider": "bunny" if bunny else None
    }


@router.post("/upload-story")
async def upload_story(
    file: UploadFile = File(...),
    user_id: str = Form(...)
):
    """
    Upload story image to Bunny Storage (stories folder).
    Returns CDN URL and bunny_path for later cleanup.
    """
    try:
        # Validate file type
        if not file.content_type or not file.content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="File must be an image")
        
        # Validate user_id
        try:
            uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid user_id format")
        
        # Get Bunny service
        bunny = get_bunny_storage()
        if not bunny:
            raise HTTPException(status_code=503, detail="Upload service not available")
        
        # Read file
        file_content = await file.read()
        
        # Validate size (max 5MB)
        if len(file_content) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File size must be less than 5MB")
        
        # Generate unique filename
        from datetime import datetime
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        filename = f"{user_id}_{timestamp}.png"
        folder = f"stories/{user_id}"
        bunny_path = f"{folder}/{filename}"
        
        # Upload to Bunny
        url = await bunny.upload_file(file_content, folder, filename)
        
        logger.info(f"Story uploaded for user {user_id}: {url}")
        
        return {
            "success": True,
            "url": url,
            "bunny_path": bunny_path,
            "message": "Story uploaded successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Story upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.post("/delete-bunny-file")
async def delete_bunny_file(
    file_path: str = Form(...)
):
    """
    Delete a file from Bunny Storage by path.
    Used for cleanup of expired stories.
    """
    try:
        bunny = get_bunny_storage()
        if not bunny:
            raise HTTPException(status_code=503, detail="Upload service not available")
        
        success = await bunny.delete_file(file_path)
        
        if success:
            logger.info(f"File deleted from Bunny: {file_path}")
            return {"success": True, "message": "File deleted"}
        else:
            return {"success": False, "message": "File deletion failed"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete error: {e}")
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")


@router.post("/generate-cover-art")
async def generate_cover_art(data: dict):
    """
    Gera uma imagem artística de capa baseada no Mapa Astral do usuário.
    Usa DALL-E 3 para gerar a imagem e faz upload para Bunny CDN.
    """
    import httpx
    import time
    from datetime import datetime
    from config import get_settings
    from services.supabase_client import get_supabase_client
    
    user_id = data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    
    logger.info(f"[CoverArt] 🎨 INÍCIO — user={user_id}")
    start_time = time.time()
    
    try:
        uuid.UUID(user_id)
    except ValueError:
        logger.error(f"[CoverArt] ❌ user_id inválido: {user_id}")
        raise HTTPException(status_code=400, detail="Invalid user_id format")
    
    settings = get_settings()
    
    if not settings.openai_api_key:
        logger.error("[CoverArt] ❌ OPENAI_API_KEY não configurada")
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")
    
    logger.info(f"[CoverArt] ✅ Step 1: API Key presente (***{settings.openai_api_key[-4:]})")
    
    # ── Step 2: Buscar mapa astral ──
    try:
        supabase = get_supabase_client()
        result = supabase.table("mapas_astrais") \
            .select("sol_signo, lua_signo, ascendente_signo, mc_signo") \
            .eq("user_id", user_id) \
            .execute()
        
        if not result.data or len(result.data) == 0:
            logger.error(f"[CoverArt] ❌ Step 2: Mapa astral não encontrado para user={user_id}")
            raise HTTPException(status_code=404, detail="Mapa astral não encontrado. Gere seu MAC primeiro.")
        
        mapa = result.data[0]
        sol = mapa.get("sol_signo", "Aries")
        lua = mapa.get("lua_signo", "Cancer")
        asc = mapa.get("ascendente_signo", "Leo")
        mc = mapa.get("mc_signo", "Capricorn")
        
        logger.info(f"[CoverArt] ✅ Step 2: MAC encontrado — Sol:{sol}, Lua:{lua}, Asc:{asc}, MC:{mc}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CoverArt] ❌ Step 2: Erro Supabase: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar mapa astral")
    
    # ── Step 3: Gerar prompt ──
    SIGN_ELEMENTS = {
        'Ari': 'Fire', 'Tau': 'Earth', 'Gem': 'Air', 'Can': 'Water',
        'Leo': 'Fire', 'Vir': 'Earth', 'Lib': 'Air', 'Sco': 'Water',
        'Sag': 'Fire', 'Cap': 'Earth', 'Aqu': 'Air', 'Pis': 'Water',
        'Áries': 'Fire', 'Touro': 'Earth', 'Gêmeos': 'Air', 'Câncer': 'Water',
        'Leão': 'Fire', 'Virgem': 'Earth', 'Libra': 'Air', 'Escorpião': 'Water',
        'Sagitário': 'Fire', 'Capricórnio': 'Earth', 'Aquário': 'Air', 'Peixes': 'Water'
    }
    
    ELEMENT_VISUALS = {
        'Fire': 'intense warm tones (deep crimson, burning orange, molten gold), flames, solar flares',
        'Earth': 'rich earthy tones (deep emerald, amber, terracotta), crystals, mountains, ancient roots',
        'Air': 'ethereal cool tones (silver, sky blue, lavender, pearl white), wind currents, light rays',
        'Water': 'deep ocean tones (midnight blue, turquoise, deep purple), ocean waves, moonlight reflections'
    }
    
    sol_el = SIGN_ELEMENTS.get(sol[:3], SIGN_ELEMENTS.get(sol, 'Fire'))
    lua_el = SIGN_ELEMENTS.get(lua[:3], SIGN_ELEMENTS.get(lua, 'Water'))
    
    prompt = (
        f"Create a stunning mystical wide banner artwork (landscape 1200x400 ratio) for a spiritual profile. "
        f"This person has Sun in {sol} ({sol_el} element), Moon in {lua} ({lua_el} element), "
        f"Ascendant in {asc}, Midheaven in {mc}. "
        f"PRIMARY COLOR PALETTE: {ELEMENT_VISUALS.get(sol_el, ELEMENT_VISUALS['Fire'])}. "
        f"SECONDARY ACCENTS: {ELEMENT_VISUALS.get(lua_el, ELEMENT_VISUALS['Water'])}. "
        f"Include the zodiac constellation pattern of {sol} glowing in the center, "
        f"and the constellation of {lua} subtly woven into the background. "
        f"Add a luminous crescent moon with {lua} energy on one side. "
        f"Style: hyper-detailed digital art, cosmic nebulae, sacred geometry, stardust particles, "
        f"ethereal glow effects, mystical luminescence. "
        f"NO text, NO letters, NO words, NO numbers. Purely visual art. Ultra high quality."
    )
    
    logger.info(f"[CoverArt] ✅ Step 3: Prompt gerado ({len(prompt)} chars)")
    
    # ── Step 4: Chamar DALL-E 3 ──
    try:
        dalle_start = time.time()
        async with httpx.AsyncClient(timeout=90.0) as client:
            logger.info(f"[CoverArt] 🔄 Step 4: Chamando DALL-E 3 (timeout=90s)...")
            dalle_resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "dall-e-3",
                    "prompt": prompt,
                    "n": 1,
                    "size": "1792x1024",
                    "quality": "standard",
                    "response_format": "b64_json"
                }
            )
            dalle_elapsed = time.time() - dalle_start
            
            if dalle_resp.status_code != 200:
                error_detail = dalle_resp.text[:500]
                logger.error(f"[CoverArt] ❌ Step 4: DALL-E retornou HTTP {dalle_resp.status_code} em {dalle_elapsed:.1f}s — {error_detail}")
                raise HTTPException(
                    status_code=502, 
                    detail=f"Erro na geração de imagem (HTTP {dalle_resp.status_code})"
                )
            
            b64_data = dalle_resp.json()["data"][0]["b64_json"]
            logger.info(f"[CoverArt] ✅ Step 4: DALL-E gerou imagem em {dalle_elapsed:.1f}s — b64 recebido ({len(b64_data)} chars)")
        
        # ── Step 5: Decodificar imagem base64 ──
        import base64
        image_bytes = base64.b64decode(b64_data)
        logger.info(f"[CoverArt] ✅ Step 5: Imagem decodificada — {len(image_bytes)} bytes")
        
        # ── Step 6: Upload para Bunny CDN ──
        bunny = get_bunny_storage()
        if not bunny:
            logger.error("[CoverArt] ❌ Step 6: BunnyStorage não disponível")
            raise HTTPException(status_code=503, detail="Serviço de upload não disponível")
        
        upload_start = time.time()
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        filename = f"{user_id}_{timestamp}_cover.png"
        logger.info(f"[CoverArt] 🔄 Step 6: Enviando para Bunny CDN — {filename}")
        cdn_url = await bunny.upload_file(image_bytes, "covers", filename)
        upload_elapsed = time.time() - upload_start
        logger.info(f"[CoverArt] ✅ Step 6: Upload Bunny OK em {upload_elapsed:.1f}s — {cdn_url}")
        
        # ── Step 7: Atualizar community_profiles ──
        try:
            supabase.table("community_profiles") \
                .update({"cover_image": cdn_url}) \
                .eq("user_id", user_id) \
                .execute()
            logger.info(f"[CoverArt] ✅ Step 7: community_profiles atualizado")
        except Exception as e:
            logger.warning(f"[CoverArt] ⚠️ Step 7: Falha ao atualizar profile (não crítico): {e}")
        
        total_elapsed = time.time() - start_time
        logger.info(f"[CoverArt] 🎉 CONCLUÍDO em {total_elapsed:.1f}s — user={user_id} — {cdn_url}")
        
        return {
            "success": True,
            "url": cdn_url,
            "message": "Cover art generated successfully"
        }
        
    except HTTPException:
        raise
    except httpx.TimeoutException as e:
        elapsed = time.time() - start_time
        logger.error(f"[CoverArt] ❌ TIMEOUT após {elapsed:.1f}s — user={user_id} — {e}")
        raise HTTPException(
            status_code=504, 
            detail="Timeout na geração de imagem. Tente novamente em alguns minutos."
        )
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[CoverArt] ❌ ERRO INESPERADO após {elapsed:.1f}s — user={user_id} — {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao gerar capa: {str(e)}")

