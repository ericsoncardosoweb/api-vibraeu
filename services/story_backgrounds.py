"""
Story Backgrounds Service
Generates AI background images for story editor using DALL-E 3.
Runs weekly to generate 5 new backgrounds with varied themes.
"""

import hashlib
import base64
import asyncio
import random
import io
import time
from datetime import datetime
from typing import List, Dict, Optional
from loguru import logger

import httpx
from config import get_settings
from services.bunny_storage import get_bunny_storage


# ── Theme Prompt Pools ────────────────────────────────────────────────────────
# Each theme has multiple style variants to ensure variety.
# All prompts end with "NO text, NO letters, NO words, NO numbers" for safety.

THEME_PROMPTS = {
    "signos": [
        {
            "style": "nebulosa_aries",
            "prompt": "Mystical Aries ram constellation glowing in deep space, fiery red and gold cosmic nebula, swirling stardust particles, ethereal light rays, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "nebulosa_touro",
            "prompt": "Majestic Taurus bull constellation shining in emerald and gold cosmic nebula, ancient star formations, crystalline energy, earth-toned cosmic dust, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "nebulosa_gemeos",
            "prompt": "Twin Gemini constellation in silvery-blue cosmic nebula, dual energy streams intertwining, mercurial light, airy ethereal atmosphere, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "nebulosa_cancer",
            "prompt": "Cancer crab constellation in deep ocean-blue cosmic nebula, moonlit silver glow, protective shell of starlight, flowing water-like energy, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "nebulosa_leao",
            "prompt": "Regal Leo lion constellation blazing in golden cosmic nebula, solar flares, majestic mane of light, warm amber and orange tones, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "nebulosa_virgem",
            "prompt": "Elegant Virgo constellation in soft green and white cosmic nebula, delicate crystalline formations, pure ethereal light, botanical cosmic elements, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "nebulosa_libra",
            "prompt": "Balanced Libra scales constellation in rose gold and lavender cosmic nebula, harmonious energy waves, symmetrical light patterns, peaceful atmosphere, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "nebulosa_escorpiao",
            "prompt": "Intense Scorpio constellation in deep crimson and black cosmic nebula, transformative energy, phoenix-like light, mysterious dark beauty, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "nebulosa_sagitario",
            "prompt": "Adventurous Sagittarius archer constellation in purple and turquoise cosmic nebula, expansive horizon, shooting star trails, optimistic cosmic energy, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "nebulosa_capricornio",
            "prompt": "Ambitious Capricorn sea-goat constellation in dark teal and silver cosmic nebula, mountain peaks of starlight, disciplined geometric patterns, ancient wisdom energy, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "nebulosa_aquario",
            "prompt": "Visionary Aquarius water-bearer constellation in electric blue and violet cosmic nebula, innovative energy streams, futuristic cosmic waves, revolutionary light, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "nebulosa_peixes",
            "prompt": "Dreamy Pisces twin fish constellation in iridescent sea-green and violet cosmic nebula, underwater cosmic world, bioluminescent particles, mystical ocean of stars, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
    ],
    "lua": [
        {
            "style": "lua_cheia_oceano",
            "prompt": "Enormous full moon rising over dark mystical ocean, bioluminescent waves crashing on shore, silver moonlight reflection path on water, ethereal mist, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "lua_crescente_floresta",
            "prompt": "Crescent moon glowing above enchanted dark forest, fireflies and magical particles floating, soft blue and silver moonlight filtering through ancient trees, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "lua_nova_cosmos",
            "prompt": "New moon phase in vast cosmic space, dark silhouette against colorful nebula, subtle corona of light, stars reflected in calm cosmic waters below, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "lua_minguante_deserto",
            "prompt": "Waning moon over surreal crystal desert landscape, purple and indigo sky, sand dunes reflecting moonlight, lone ancient tree silhouette, spiritual atmosphere, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "lua_sangue",
            "prompt": "Blood moon lunar eclipse in dramatic crimson sky, ancient temple silhouette below, powerful cosmic energy radiating, deep red and orange tones, mystical atmosphere, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "lua_azul",
            "prompt": "Rare blue moon in deep sapphire sky, floating crystal islands catching moonlight, waterfalls of light falling into cosmic void, serene and magical, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "lua_montanha",
            "prompt": "Giant moon behind snow-capped mountain peaks, northern lights dancing below, reflection in alpine lake, pristine and ethereal atmosphere, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "lua_jardim",
            "prompt": "Full moon illuminating a mystical night garden, glowing flowers and luminescent butterflies, dew drops catching moonlight, magical botanical paradise, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
    ],
    "cabala": [
        {
            "style": "arvore_vida_cosmica",
            "prompt": "Kabbalistic Tree of Life floating in cosmic space, ten luminous sephirot spheres connected by golden light paths, sacred geometry, divine energy radiating, purple and gold tones, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "flor_vida",
            "prompt": "Sacred Flower of Life geometry pattern glowing in deep space, overlapping circles of light, ancient wisdom energy, emerald green and gold, cosmic particles flowing through patterns, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "merkaba_luz",
            "prompt": "Luminous Merkaba sacred geometry star shape radiating divine light, spinning energy field, crystalline structure, white and violet light, spiritual ascension energy, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "geometria_metatron",
            "prompt": "Metatron's Cube sacred geometry in cosmic void, intricate interconnected lines of light, all Platonic solids visible within, golden ratio spirals, deep indigo background, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "portal_cabalistico",
            "prompt": "Ancient Kabbalistic portal opening in cosmic space, concentric rings of sacred symbols glowing, divine light streaming through, mystical stairway of consciousness, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "sephirot_dourado",
            "prompt": "Ten Sephirot spheres arranged in Tree of Life formation, each glowing different color, golden pathways connecting them, cosmic background with Hebrew-inspired geometric light patterns, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
    ],
    "ceu": [
        {
            "style": "aurora_boreal_verde",
            "prompt": "Breathtaking aurora borealis dancing across night sky in vivid greens and purples, reflected in pristine mountain lake, snow-covered peaks, stars visible above, portrait orientation 9:16, ultra detailed photography style. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "via_lactea",
            "prompt": "Stunning Milky Way galaxy arch across dark night sky, thousands of stars visible, silhouetted landscape below, warm and cool tones blending, cosmic perspective, portrait orientation 9:16, ultra detailed photography style. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "por_do_sol_cosmico",
            "prompt": "Surreal sunset with multiple color layers from deep orange to violet to cosmic blue, clouds painted with light, transition from earthly sunset to cosmic starfield above, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "nuvens_douradas",
            "prompt": "Majestic golden hour clouds seen from above, sun rays streaming through cloud formations, heavenly atmosphere, warm amber and rose gold colors, divine light, portrait orientation 9:16, ultra detailed photography style. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "ceu_estrelado_deserto",
            "prompt": "Desert night sky filled with millions of stars, spiral galaxy visible, sand dunes in warm moonlight below, perfect stillness, infinite cosmic beauty, portrait orientation 9:16, ultra detailed photography style. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "tempestade_cosmica",
            "prompt": "Dramatic cosmic storm clouds with lightning and cosmic energy, purple and electric blue bolts illuminating mystical sky, powerful and beautiful, cosmic scale weather phenomenon, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "nuvens_iridescentes",
            "prompt": "Rare iridescent nacreous clouds glowing in pastel rainbow colors against twilight sky, mother-of-pearl effect, ethereal and otherworldly atmospheric beauty, portrait orientation 9:16, ultra detailed photography style. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "supernova_ceu",
            "prompt": "Supernova explosion visible in night sky, expanding rings of colorful cosmic gas, ancient forest silhouette below witnessing cosmic event, awe-inspiring scale, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
    ],
    "inspiracao": [
        {
            "style": "lotus_cosmica",
            "prompt": "Luminous lotus flower blooming in cosmic space, petals made of starlight and cosmic energy, soft pink and violet gradients, spiritual awakening energy, sacred pool of light, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "borboleta_transformacao",
            "prompt": "Magnificent cosmic butterfly with wings made of galaxies and nebulae, transformative energy swirling, chrysalis of light dissolving, rebirth symbolism, vibrant colors, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "caminho_luz",
            "prompt": "Ethereal pathway of light stretching into distant cosmic horizon, lined with glowing willow trees, particles of hope floating upward, warm golden and soft cyan gradient, serene journey, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "cristal_energia",
            "prompt": "Giant amethyst crystal formation radiating healing energy in mystical cave, bioluminescent moss and flowers, purple and turquoise light refracting through crystal facets, spiritual power, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "fenix_renascimento",
            "prompt": "Majestic phoenix bird rising from cosmic ashes, wings spread wide with feathers of fire and gold, transformation energy spiraling, dark to light gradient background, rebirth and power, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "mandala_cosmica",
            "prompt": "Intricate cosmic mandala pattern radiating from center, layers of sacred geometry and organic floral patterns, deep teal and gold colors, meditative and harmonious energy, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "oceano_estrelas",
            "prompt": "Surreal scene where ocean meets starfield, waves made of liquid starlight, bioluminescent creatures swimming, boundary between water and cosmos dissolving, dreamy atmosphere, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "jardim_cosmico",
            "prompt": "Enchanted cosmic garden with glowing flowers and plants from different galaxies, floating luminous seeds, ethereal mist, vibrant colors against dark cosmic background, peaceful beauty, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
    ],
    "elementos": [
        {
            "style": "elemento_fogo",
            "prompt": "Primordial Fire element in cosmic space, swirling flames forming sacred spirals, molten lava rivers in starfield, intense orange red and gold energy radiating outward, passionate transformative force, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "elemento_terra",
            "prompt": "Ancient Earth element in cosmic space, towering crystal mountains emerging from cosmic soil, roots of light connecting deep underground, emerald green and brown tones with golden veins, grounding stability energy, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "elemento_ar",
            "prompt": "Ethereal Air element in cosmic space, swirling winds of light forming tornado spirals through clouds of stardust, feathers of energy floating freely, soft lavender and sky blue tones, intellectual freedom energy, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "elemento_agua",
            "prompt": "Deep Water element in cosmic space, cosmic ocean waves merging with nebula, bioluminescent depths revealing ancient mysteries, flowing liquid starlight, deep teal and sapphire blue tones, emotional intuitive energy, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
    ],
    "aspectos": [
        {
            "style": "aspecto_conjuncao",
            "prompt": "Celestial Conjunction aspect, two brilliant cosmic spheres merging into one unified light source, fusion of energies creating powerful golden glow, sacred union symbolism, radiant beams spreading outward, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "aspecto_oposicao",
            "prompt": "Celestial Opposition aspect, two cosmic bodies facing each other across vast cosmic space, tension and balance between light and shadow, red and blue energies pulling and pushing, dramatic polarity, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "aspecto_trigono",
            "prompt": "Celestial Trine aspect, three cosmic points forming perfect luminous triangle in space, harmonious energy flowing between them, soft golden and emerald green streams of light, effortless cosmic harmony, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "aspecto_quadratura",
            "prompt": "Celestial Square aspect, four cosmic energies at sharp angles creating dynamic tension, electric bolts between the points, deep crimson and violet storm energies, challenging but transformative cosmic power, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "aspecto_sextil",
            "prompt": "Celestial Sextile aspect, two cosmic lights connected by a gentle bridge of stardust, opportunities flowing between them, soft pastel rainbow energy streams, subtle supportive cosmic connection, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
    ],
    "planetas": [
        {
            "style": "planeta_sol",
            "prompt": "Majestic Sun as cosmic deity radiating infinite golden light in deep space, solar flares forming crown of fire, warm amber and white core energy, life-giving vital force, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "planeta_lua",
            "prompt": "Mystical Moon goddess in cosmic space, all moon phases arrayed in luminous arc, silver and pearl light reflecting on cosmic waters below, feminine intuitive energy, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "planeta_mercurio",
            "prompt": "Swift Mercury planet with wings of light in cosmic space, streams of information and communication flowing as golden threads, quicksilver surface reflecting cosmos, intellectual energy, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "planeta_venus",
            "prompt": "Beautiful Venus planet glowing with rose gold and soft pink light in cosmic space, surrounded by rings of flowers made of starlight, love and beauty energy radiating outward, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "planeta_marte",
            "prompt": "Fierce Mars planet blazing with crimson energy in cosmic space, warrior spirit fire surrounding it, powerful red and orange volcanic surface, determination and action force, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "planeta_jupiter",
            "prompt": "Magnificent Jupiter giant planet in cosmic space, swirling bands of amber and cream gas, expansive energy spreading outward, abundant golden light blessing cosmos, wisdom and growth force, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "planeta_saturno",
            "prompt": "Ancient Saturn planet with luminous crystalline rings in cosmic space, disciplined geometric ice formations orbiting, deep indigo and silver tones, structured wisdom and time energy, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "planeta_urano",
            "prompt": "Revolutionary Uranus planet tilted on its axis in cosmic space, electric blue and cyan energy bolts radiating, unconventional tilted rings of light, innovation and awakening cosmic force, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "planeta_netuno",
            "prompt": "Dreamy Neptune planet dissolving into cosmic mist, deep ocean blue and violet swirls merging with nebula, mystical underwater cosmic realm, spiritual transcendence and imagination energy, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
        {
            "style": "planeta_plutao",
            "prompt": "Mysterious Pluto planet in the darkest depths of cosmic space, transformative phoenix fire emerging from its surface, deep magenta and black tones, death and rebirth cycle energy, portrait orientation 9:16, ultra detailed digital art. NO text, NO letters, NO words, NO numbers."
        },
    ],
}


def _hash_prompt(prompt: str) -> str:
    """Generate SHA-256 hash of a prompt for deduplication."""
    return hashlib.sha256(prompt.encode()).hexdigest()[:32]


def _get_all_prompts_flat() -> List[Dict]:
    """Flatten all theme prompts into a single list with theme info."""
    all_prompts = []
    for theme, prompts in THEME_PROMPTS.items():
        for p in prompts:
            all_prompts.append({
                "theme": theme,
                "style": p["style"],
                "prompt": p["prompt"],
                "hash": _hash_prompt(p["prompt"])
            })
    return all_prompts


async def get_used_hashes() -> set:
    """Get all prompt hashes already used from the database."""
    try:
        from services.supabase_client import get_supabase_client
        supabase = get_supabase_client()
        
        result = supabase.table("story_backgrounds") \
            .select("prompt_hash") \
            .execute()
        
        return {r["prompt_hash"] for r in (result.data or [])}
    except Exception as e:
        logger.warning(f"[StoryBG] Could not fetch used hashes: {e}")
        return set()


async def generate_thumbnail(image_bytes: bytes, max_width: int = 300) -> bytes:
    """Generate a thumbnail from image bytes using Pillow."""
    try:
        from PIL import Image
        
        img = Image.open(io.BytesIO(image_bytes))
        
        # Calculate new size maintaining aspect ratio
        ratio = max_width / img.width
        new_height = int(img.height * ratio)
        
        img_thumb = img.resize((max_width, new_height), Image.LANCZOS)
        
        buffer = io.BytesIO()
        img_thumb.save(buffer, format="WEBP", quality=80)
        return buffer.getvalue()
        
    except ImportError:
        logger.warning("[StoryBG] Pillow not installed, skipping thumbnail generation")
        return None
    except Exception as e:
        logger.warning(f"[StoryBG] Thumbnail generation failed: {e}")
        return None


async def generate_single_background(
    prompt_info: Dict,
    settings,
    bunny,
    supabase
) -> Optional[Dict]:
    """
    Generate a single background image:
    1. Call DALL-E 3
    2. Upload full image + thumbnail to Bunny CDN
    3. Save record in database
    """
    prompt = prompt_info["prompt"]
    theme = prompt_info["theme"]
    style = prompt_info["style"]
    prompt_hash = prompt_info["hash"]
    
    logger.info(f"[StoryBG] Generating: theme={theme}, style={style}")
    start_time = time.time()
    
    try:
        # Step 1: Call DALL-E 3
        async with httpx.AsyncClient(timeout=90.0) as client:
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
                    "size": "1024x1792",
                    "quality": "standard",
                    "response_format": "b64_json"
                }
            )
        
        if dalle_resp.status_code != 200:
            logger.error(f"[StoryBG] DALL-E error HTTP {dalle_resp.status_code}: {dalle_resp.text[:300]}")
            return None
        
        b64_data = dalle_resp.json()["data"][0]["b64_json"]
        image_bytes = base64.b64decode(b64_data)
        dalle_elapsed = time.time() - start_time
        logger.info(f"[StoryBG] DALL-E generated in {dalle_elapsed:.1f}s ({len(image_bytes)} bytes)")
        
        # Step 2: Generate thumbnail
        thumb_bytes = await generate_thumbnail(image_bytes)
        
        # Step 3: Upload to Bunny CDN
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        now = datetime.utcnow()
        week_number = now.isocalendar()[1]
        year = now.year
        
        # Full image
        filename = f"{theme}_{style}_{timestamp}.png"
        folder = "story-backgrounds"
        bunny_path = f"{folder}/{filename}"
        image_url = await bunny.upload_file(image_bytes, folder, filename)
        logger.info(f"[StoryBG] Full image uploaded: {image_url}")
        
        # Thumbnail
        thumb_url = None
        if thumb_bytes:
            thumb_filename = f"thumb_{theme}_{style}_{timestamp}.webp"
            thumb_folder = "story-backgrounds/thumbs"
            thumb_url = await bunny.upload_file(thumb_bytes, thumb_folder, thumb_filename)
            logger.info(f"[StoryBG] Thumbnail uploaded: {thumb_url}")
        
        # Step 4: Save to database
        record = {
            "image_url": image_url,
            "thumb_url": thumb_url,
            "bunny_path": bunny_path,
            "theme": theme,
            "style": style,
            "prompt_hash": prompt_hash,
            "week_number": week_number,
            "year": year,
            "active": True
        }
        
        supabase.table("story_backgrounds").insert(record).execute()
        
        total_elapsed = time.time() - start_time
        logger.info(f"[StoryBG] ✅ Background saved: {theme}/{style} in {total_elapsed:.1f}s")
        
        return record
        
    except Exception as e:
        logger.error(f"[StoryBG] ❌ Failed to generate {theme}/{style}: {e}")
        return None


async def generate_weekly_backgrounds(count: int = 5) -> Dict:
    """
    Generate weekly story backgrounds.
    Selects `count` unused prompts across themes and generates images.
    
    Returns:
        Dict with success status and details
    """
    logger.info(f"[StoryBG] 🎨 Starting weekly generation of {count} backgrounds...")
    
    settings = get_settings()
    
    if not settings.openai_api_key:
        logger.error("[StoryBG] ❌ OpenAI API key not configured")
        return {"success": False, "error": "OpenAI API key not configured"}
    
    bunny = get_bunny_storage()
    if not bunny:
        logger.error("[StoryBG] ❌ Bunny Storage not available")
        return {"success": False, "error": "Bunny Storage not available"}
    
    # Get supabase client
    try:
        from services.supabase_client import get_supabase_client
        supabase = get_supabase_client()
    except Exception as e:
        logger.error(f"[StoryBG] ❌ Supabase error: {e}")
        return {"success": False, "error": f"Database error: {e}"}
    
    # Check if enabled
    try:
        setting_result = supabase.table("system_settings") \
            .select("value") \
            .eq("key", "story_bg_generation_enabled") \
            .execute()
        
        if setting_result.data and setting_result.data[0].get("value") == "false":
            logger.info("[StoryBG] ⏸️ Generation is disabled via system settings")
            return {"success": True, "message": "Generation disabled", "generated": 0}
    except Exception:
        pass  # If setting doesn't exist, default to enabled
    
    # Get used hashes
    used_hashes = await get_used_hashes()
    logger.info(f"[StoryBG] {len(used_hashes)} prompts already used")
    
    # Get available prompts (not yet used)
    all_prompts = _get_all_prompts_flat()
    available = [p for p in all_prompts if p["hash"] not in used_hashes]
    
    if not available:
        logger.warning("[StoryBG] ⚠️ All prompts have been used! Resetting...")
        # Reset: mark all as inactive and start fresh
        try:
            supabase.table("story_backgrounds") \
                .update({"active": False}) \
                .neq("id", "00000000-0000-0000-0000-000000000000") \
                .execute()
            # Clear used hashes and retry
            available = all_prompts
            logger.info("[StoryBG] Pool reset. All previous backgrounds marked inactive.")
        except Exception as e:
            logger.error(f"[StoryBG] Reset failed: {e}")
            return {"success": False, "error": "All prompts used and reset failed"}
    
    # Select prompts ensuring theme variety
    selected = []
    themes_used = set()
    random.shuffle(available)
    
    # First pass: one per theme
    for p in available:
        if p["theme"] not in themes_used and len(selected) < count:
            selected.append(p)
            themes_used.add(p["theme"])
    
    # Second pass: fill remaining slots
    for p in available:
        if p not in selected and len(selected) < count:
            selected.append(p)
    
    logger.info(f"[StoryBG] Selected {len(selected)} prompts: {[s['theme']+'/'+s['style'] for s in selected]}")
    
    # Generate each background with rate limiting
    generated = []
    errors = 0
    
    for i, prompt_info in enumerate(selected):
        result = await generate_single_background(prompt_info, settings, bunny, supabase)
        
        if result:
            generated.append(result)
        else:
            errors += 1
        
        # Rate limit: wait 3s between DALL-E calls
        if i < len(selected) - 1:
            await asyncio.sleep(3)
    
    summary = {
        "success": True,
        "generated": len(generated),
        "errors": errors,
        "total_available": len(all_prompts),
        "total_used": len(used_hashes) + len(generated),
        "themes": list({g["theme"] for g in generated})
    }
    
    logger.info(f"[StoryBG] 🎉 Generation complete: {summary}")
    return summary


async def list_active_backgrounds(limit: int = 30) -> List[Dict]:
    """List active story backgrounds ordered by most recent."""
    try:
        from services.supabase_client import get_supabase_client
        supabase = get_supabase_client()
        
        result = supabase.table("story_backgrounds") \
            .select("id, image_url, thumb_url, theme, style, created_at") \
            .eq("active", True) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        
        return result.data or []
    except Exception as e:
        logger.error(f"[StoryBG] Error listing backgrounds: {e}")
        return []


# ── Theme Catalog Labels ─────────────────────────────────────────────────────

THEME_LABELS = {
    "signos": {"label": "Signos", "emoji": "♈", "description": "Constelações dos 12 signos do zodíaco"},
    "lua": {"label": "Lua", "emoji": "🌙", "description": "Fases e cenários lunares"},
    "cabala": {"label": "Cabala", "emoji": "✡", "description": "Geometria sagrada e árvore da vida"},
    "ceu": {"label": "Céu", "emoji": "🌌", "description": "Auroras, Via Láctea e fenômenos celestes"},
    "inspiracao": {"label": "Inspiração", "emoji": "🌸", "description": "Símbolos de transformação e beleza"},
    "elementos": {"label": "Elementos", "emoji": "🔥", "description": "Fogo, Terra, Ar e Água"},
    "aspectos": {"label": "Aspectos", "emoji": "⭐", "description": "Conjunção, Oposição, Trígono, etc."},
    "planetas": {"label": "Planetas", "emoji": "🪐", "description": "Sol, Lua, Mercúrio a Plutão"},
}

STYLE_LABELS = {
    # Signos
    "nebulosa_aries": "Áries", "nebulosa_touro": "Touro", "nebulosa_gemeos": "Gêmeos",
    "nebulosa_cancer": "Câncer", "nebulosa_leao": "Leão", "nebulosa_virgem": "Virgem",
    "nebulosa_libra": "Libra", "nebulosa_escorpiao": "Escorpião", "nebulosa_sagitario": "Sagitário",
    "nebulosa_capricornio": "Capricórnio", "nebulosa_aquario": "Aquário", "nebulosa_peixes": "Peixes",
    # Lua
    "lua_cheia_oceano": "Lua Cheia", "lua_crescente_floresta": "Lua Crescente",
    "lua_nova_cosmos": "Lua Nova", "lua_minguante_deserto": "Lua Minguante",
    "lua_sangue": "Lua de Sangue", "lua_azul": "Lua Azul",
    "lua_montanha": "Lua na Montanha", "lua_jardim": "Lua no Jardim",
    # Cabala
    "arvore_vida_cosmica": "Árvore da Vida", "flor_vida": "Flor da Vida",
    "merkaba_luz": "Merkaba", "geometria_metatron": "Cubo de Metatron",
    "portal_cabalistico": "Portal Cabalístico", "sephirot_dourado": "Sephirot",
    # Céu
    "aurora_boreal_verde": "Aurora Boreal", "via_lactea": "Via Láctea",
    "por_do_sol_cosmico": "Pôr do Sol", "nuvens_douradas": "Nuvens Douradas",
    "ceu_estrelado_deserto": "Céu Estrelado", "tempestade_cosmica": "Tempestade Cósmica",
    "nuvens_iridescentes": "Nuvens Iridescentes", "supernova_ceu": "Supernova",
    # Inspiração
    "lotus_cosmica": "Lótus Cósmica", "borboleta_transformacao": "Borboleta",
    "caminho_luz": "Caminho de Luz", "cristal_energia": "Cristal",
    "fenix_renascimento": "Fênix", "mandala_cosmica": "Mandala",
    "oceano_estrelas": "Oceano de Estrelas", "jardim_cosmico": "Jardim Cósmico",
    # Elementos
    "elemento_fogo": "Fogo", "elemento_terra": "Terra",
    "elemento_ar": "Ar", "elemento_agua": "Água",
    # Aspectos
    "aspecto_conjuncao": "Conjunção", "aspecto_oposicao": "Oposição",
    "aspecto_trigono": "Trígono", "aspecto_quadratura": "Quadratura",
    "aspecto_sextil": "Sextil",
    # Planetas
    "planeta_sol": "Sol", "planeta_lua": "Lua", "planeta_mercurio": "Mercúrio",
    "planeta_venus": "Vênus", "planeta_marte": "Marte", "planeta_jupiter": "Júpiter",
    "planeta_saturno": "Saturno", "planeta_urano": "Urano",
    "planeta_netuno": "Netuno", "planeta_plutao": "Plutão",
}


def get_available_themes() -> List[Dict]:
    """
    Return full theme catalog for admin UI.
    Each theme includes its styles with labels and used/available status.
    """
    themes = []
    for theme_key, prompts in THEME_PROMPTS.items():
        meta = THEME_LABELS.get(theme_key, {"label": theme_key, "emoji": "✨", "description": ""})
        styles = []
        for p in prompts:
            styles.append({
                "style": p["style"],
                "label": STYLE_LABELS.get(p["style"], p["style"]),
            })
        themes.append({
            "key": theme_key,
            "label": meta["label"],
            "emoji": meta["emoji"],
            "description": meta["description"],
            "styles": styles,
            "count": len(styles),
        })
    return themes


async def generate_selected_backgrounds(
    selected_styles: List[str],
) -> Dict:
    """
    Generate backgrounds for specific admin-selected styles.
    
    Args:
        selected_styles: List of style keys to generate (e.g. ["nebulosa_aries", "elemento_fogo"])
    
    Returns:
        Dict with results per item for progress tracking.
    """
    logger.info(f"[StoryBG] 🎨 Admin manual generation: {len(selected_styles)} items")
    
    settings = get_settings()
    
    if not settings.openai_api_key:
        return {"success": False, "error": "OpenAI API key not configured"}
    
    bunny = get_bunny_storage()
    if not bunny:
        return {"success": False, "error": "Bunny Storage not available"}
    
    try:
        from services.supabase_client import get_supabase_client
        supabase = get_supabase_client()
    except Exception as e:
        return {"success": False, "error": f"Database error: {e}"}
    
    # Build lookup from all prompts
    all_prompts = _get_all_prompts_flat()
    prompt_map = {p["style"]: p for p in all_prompts}
    
    # Filter to requested styles
    to_generate = []
    for style_key in selected_styles:
        if style_key in prompt_map:
            to_generate.append(prompt_map[style_key])
        else:
            logger.warning(f"[StoryBG] Style not found: {style_key}")
    
    if not to_generate:
        return {"success": False, "error": "Nenhum estilo válido selecionado"}
    
    # Generate each
    results = []
    generated_count = 0
    error_count = 0
    
    for i, prompt_info in enumerate(to_generate):
        item_result = {
            "index": i,
            "total": len(to_generate),
            "theme": prompt_info["theme"],
            "style": prompt_info["style"],
            "label": STYLE_LABELS.get(prompt_info["style"], prompt_info["style"]),
            "theme_label": THEME_LABELS.get(prompt_info["theme"], {}).get("label", prompt_info["theme"]),
        }
        
        result = await generate_single_background(prompt_info, settings, bunny, supabase)
        
        if result:
            item_result["success"] = True
            item_result["image_url"] = result.get("image_url")
            item_result["thumb_url"] = result.get("thumb_url")
            generated_count += 1
        else:
            item_result["success"] = False
            error_count += 1
        
        results.append(item_result)
        
        # Rate limit between DALL-E calls
        if i < len(to_generate) - 1:
            await asyncio.sleep(3)
    
    summary = {
        "success": True,
        "generated": generated_count,
        "errors": error_count,
        "total_requested": len(to_generate),
        "results": results,
    }
    
    logger.info(f"[StoryBG] 🎉 Admin generation complete: {generated_count}/{len(to_generate)}")
    return summary

