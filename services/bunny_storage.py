"""
Bunny Storage service for file uploads.
Handles avatar and media uploads to BunnyCDN storage.
"""

import httpx
from typing import Optional
from loguru import logger
import uuid
from datetime import datetime

from config import get_settings


class BunnyStorageService:
    """Service for uploading files to Bunny Storage."""
    
    def __init__(self):
        self.settings = get_settings()
        
        if not self.settings.bunny_enabled:
            raise ValueError("Bunny Storage not enabled")
        
        self.zone = self.settings.bunny_storage_zone
        self.api_key = self.settings.bunny_storage_api_key
        self.hostname = self.settings.bunny_storage_hostname
        self.cdn_url = self.settings.bunny_cdn_url
        
        if not all([self.zone, self.api_key, self.hostname, self.cdn_url]):
            raise ValueError("Bunny Storage configuration incomplete")
    
    async def upload_file(
        self, 
        file_content: bytes, 
        folder: str, 
        filename: str
    ) -> str:
        """
        Upload a file to Bunny Storage.
        
        Args:
            file_content: File bytes
            folder: Folder path (e.g., 'avatars')
            filename: Target filename
            
        Returns:
            Public CDN URL of the uploaded file
        """
        # Build path
        path = f"/{self.zone}/{folder}/{filename}"
        url = f"https://{self.hostname}{path}"
        
        # Headers
        headers = {
            "AccessKey": self.api_key,
            "Content-Type": "application/octet-stream"
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.put(
                    url,
                    headers=headers,
                    content=file_content
                )
                
                response.raise_for_status()
                
                # Return CDN URL
                cdn_path = f"{folder}/{filename}"
                return f"{self.cdn_url}/{cdn_path}"
                
        except httpx.HTTPStatusError as e:
            logger.error(f"Bunny upload HTTP error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Upload failed: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Bunny upload error: {e}")
            raise Exception(f"Upload failed: {str(e)}")
    
    async def upload_avatar(
        self, 
        file_content: bytes, 
        user_id: str, 
        file_extension: str
    ) -> str:
        """
        Upload user avatar.
        
        Args:
            file_content: Image bytes
            user_id: User UUID
            file_extension: File extension (jpg, png, etc)
            
        Returns:
            Public CDN URL
        """
        # Generate unique filename
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        filename = f"{user_id}_{timestamp}.{file_extension}"
        
        return await self.upload_file(file_content, "avatars", filename)
    
    async def delete_file(self, file_path: str) -> bool:
        """
        Delete a file from Bunny Storage.
        
        Args:
            file_path: Full path to file (e.g., 'avatars/user_123.jpg')
            
        Returns:
            True if deleted successfully
        """
        path = f"/{self.zone}/{file_path}"
        url = f"https://{self.hostname}{path}"
        
        headers = {
            "AccessKey": self.api_key
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.delete(url, headers=headers)
                response.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Bunny delete error: {e}")
            return False


def get_bunny_storage() -> Optional[BunnyStorageService]:
    """Get Bunny Storage service if enabled."""
    settings = get_settings()
    if settings.bunny_enabled:
        try:
            return BunnyStorageService()
        except Exception as e:
            logger.warning(f"Bunny Storage initialization failed: {e}")
            return None
    return None
