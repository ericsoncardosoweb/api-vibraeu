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
