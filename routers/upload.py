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
    from datetime import datetime
    from config import get_settings
    
    user_id = data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    
    try:
        uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id format")
    
    settings = get_settings()
    
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")
    
    # Buscar mapa astral do usuário
    try:
        import httpx as _httpx
        headers = {
            "apikey": settings.supabase_service_key,
            "Authorization": f"Bearer {settings.supabase_service_key}",
            "Content-Type": "application/json"
        }
        
        async with _httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.supabase_url}/rest/v1/mapas_astrais?user_id=eq.{user_id}&select=sol_signo,lua_signo,ascendente_signo,mc_signo",
                headers=headers
            )
            mapa_data = resp.json()
        
        if not mapa_data or len(mapa_data) == 0:
            raise HTTPException(status_code=404, detail="Mapa astral não encontrado")
        
        mapa = mapa_data[0]
        sol = mapa.get("sol_signo", "Aries")
        lua = mapa.get("lua_signo", "Cancer")
        asc = mapa.get("ascendente_signo", "Leo")
        mc = mapa.get("mc_signo", "Capricorn")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching mapa astral: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar mapa astral")
    
    # Gerar prompt artístico
    prompt = (
        f"Create a mystical, abstract, artistic cover image for a spiritual profile. "
        f"The image should visually represent the astrological quartet: "
        f"Sun in {sol}, Moon in {lua}, Ascendant in {asc}, Midheaven in {mc}. "
        f"Use cosmic elements like nebulae, constellations, and celestial bodies. "
        f"Color palette inspired by the zodiac signs. "
        f"Wide banner format (1200x400), dreamy and ethereal style, "
        f"no text, no letters, no words, purely visual art. "
        f"High quality, digital art, vibrant colors."
    )
    
    # Chamar DALL-E 3
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
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
                    "quality": "standard"
                }
            )
            
            if dalle_resp.status_code != 200:
                logger.error(f"DALL-E error: {dalle_resp.status_code} - {dalle_resp.text}")
                raise HTTPException(status_code=502, detail="Erro ao gerar imagem com IA")
            
            image_url = dalle_resp.json()["data"][0]["url"]
        
        # Download da imagem gerada
        async with httpx.AsyncClient(timeout=30.0) as client:
            img_resp = await client.get(image_url)
            image_bytes = img_resp.content
        
        # Upload para Bunny CDN
        bunny = get_bunny_storage()
        if not bunny:
            raise HTTPException(status_code=503, detail="Upload service not available")
        
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        filename = f"{user_id}_{timestamp}_cover.png"
        cdn_url = await bunny.upload_file(image_bytes, "covers", filename)
        
        # Atualizar community_profiles
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{settings.supabase_url}/rest/v1/community_profiles?user_id=eq.{user_id}",
                headers={
                    "apikey": settings.supabase_service_key,
                    "Authorization": f"Bearer {settings.supabase_service_key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                json={"cover_image": cdn_url}
            )
        
        logger.info(f"Cover art generated for user {user_id}: {cdn_url}")
        
        return {
            "success": True,
            "url": cdn_url,
            "message": "Cover art generated successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cover art generation error: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao gerar capa: {str(e)}")

