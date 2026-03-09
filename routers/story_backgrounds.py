"""
Story Backgrounds Router
Endpoints for listing and generating AI story backgrounds.
"""

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from typing import List, Optional

router = APIRouter()


@router.get("/story-backgrounds")
async def get_story_backgrounds(
    limit: int = Query(default=30, le=50)
):
    """
    List active story backgrounds.
    Returns backgrounds ordered by most recent first.
    """
    try:
        from services.story_backgrounds import list_active_backgrounds
        
        backgrounds = await list_active_backgrounds(limit=limit)
        
        return {
            "success": True,
            "data": backgrounds,
            "count": len(backgrounds)
        }
    except Exception as e:
        logger.error(f"[StoryBG Router] Error listing backgrounds: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/story-backgrounds/themes")
async def get_themes_catalog():
    """
    Return available themes and styles for the admin generation modal.
    """
    try:
        from services.story_backgrounds import get_available_themes
        
        themes = get_available_themes()
        return {"success": True, "themes": themes}
    except Exception as e:
        logger.error(f"[StoryBG Router] Themes catalog error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/generate-story-backgrounds")
async def trigger_generate_backgrounds(
    data: dict = None
):
    """
    Manually trigger story background generation.
    Accepts specific styles selected by admin.
    Protected by API key (handled by middleware).
    """
    try:
        if data and data.get("styles"):
            # New flow: admin-selected styles
            from services.story_backgrounds import generate_selected_backgrounds
            
            styles = data.get("styles", [])
            
            logger.info(f"[StoryBG Router] Admin selected generation: {len(styles)} styles")
            
            result = await generate_selected_backgrounds(selected_styles=styles)
            return result
        else:
            # Legacy: random generation
            from services.story_backgrounds import generate_weekly_backgrounds
            
            count = 5
            if data and isinstance(data, dict):
                count = data.get("count", 5)
            
            logger.info(f"[StoryBG Router] Legacy trigger: generating {count} backgrounds")
            result = await generate_weekly_backgrounds(count=count)
            return result
        
    except Exception as e:
        logger.error(f"[StoryBG Router] Generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/story-backgrounds/stats")
async def get_backgrounds_stats():
    """
    Get stats about story backgrounds for admin dashboard.
    """
    try:
        from services.supabase_client import get_supabase_client
        supabase = get_supabase_client()
        
        # Count active backgrounds
        active_result = supabase.table("story_backgrounds") \
            .select("id", count="exact") \
            .eq("active", True) \
            .execute()
        
        # Count total backgrounds
        total_result = supabase.table("story_backgrounds") \
            .select("id", count="exact") \
            .execute()
        
        # Get last generated
        last_result = supabase.table("story_backgrounds") \
            .select("created_at, theme, style") \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        
        return {
            "success": True,
            "active_count": active_result.count or 0,
            "total_count": total_result.count or 0,
            "last_generated": last_result.data[0] if last_result.data else None
        }
        
    except Exception as e:
        logger.error(f"[StoryBG Router] Stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
