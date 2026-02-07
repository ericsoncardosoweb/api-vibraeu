"""
Frases Router — CRUD admin + API pública para consumo de frases.

Endpoints Admin (protegidos por API Key):
    GET    /admin/frases          — Listar frases com filtros
    POST   /admin/frases          — Criar frase
    PUT    /admin/frases/{id}     — Atualizar frase
    DELETE /admin/frases/{id}     — Excluir frase
    POST   /admin/frases/gerar    — Gerar frases com IA

Endpoints Públicos (via messaging ou direct):
    GET    /frases/dia/{user_id}  — 5 frases do dia filtradas pelo MAC do user
    GET    /frases/random         — Frases aleatórias com filtros
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from loguru import logger

from services.supabase_client import get_supabase_client
from services.llm_gateway import LLMGateway
from services.cache import response_cache

router = APIRouter()


# ============================================
# Models
# ============================================

class FraseCreate(BaseModel):
    texto: str
    autor: Optional[str] = None
    fonte: Optional[str] = None
    categoria: str = "inspiracao"
    signos: List[str] = []
    temas: List[str] = []
    destaque: bool = False


class FraseUpdate(BaseModel):
    texto: Optional[str] = None
    autor: Optional[str] = None
    fonte: Optional[str] = None
    categoria: Optional[str] = None
    signos: Optional[List[str]] = None
    temas: Optional[List[str]] = None
    ativo: Optional[bool] = None
    destaque: Optional[bool] = None


class GerarFrasesRequest(BaseModel):
    categoria: str = "inspiracao"
    tema: Optional[str] = None
    signo: Optional[str] = None
    quantidade: int = 5


# ============================================
# Mapa de signos normalizados
# ============================================
SIGNOS_MAP = {
    "aries": "aries", "áries": "aries",
    "touro": "touro", "taurus": "touro",
    "gemeos": "gemeos", "gêmeos": "gemeos", "gemini": "gemeos",
    "cancer": "cancer", "câncer": "cancer",
    "leao": "leao", "leão": "leao", "leo": "leao",
    "virgem": "virgem", "virgo": "virgem",
    "libra": "libra",
    "escorpiao": "escorpiao", "escorpião": "escorpiao", "scorpio": "escorpiao",
    "sagitario": "sagitario", "sagitário": "sagitario", "sagittarius": "sagitario",
    "capricornio": "capricornio", "capricórnio": "capricornio", "capricorn": "capricornio",
    "aquario": "aquario", "aquário": "aquario", "aquarius": "aquario",
    "peixes": "peixes", "pisces": "peixes",
}

def normalize_signo(signo: str) -> str:
    """Normaliza nome do signo para formato padrão."""
    return SIGNOS_MAP.get(signo.lower().strip(), signo.lower().strip())


# ============================================
# ADMIN ENDPOINTS (protegidos por API Key via main.py)
# ============================================

@router.get("/frases")
async def list_frases(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    categoria: Optional[str] = None,
    signo: Optional[str] = None,
    tema: Optional[str] = None,
    busca: Optional[str] = None,
    ativo: Optional[bool] = None,
):
    """Listar frases com filtros e paginação."""
    try:
        supabase = get_supabase_client()
        query = supabase.table("frases_inspiracao").select(
            "*", count="exact"
        ).order("created_at", desc=True)

        if categoria:
            query = query.eq("categoria", categoria)
        if signo:
            normalized = normalize_signo(signo)
            query = query.contains("signos", [normalized])
        if tema:
            query = query.contains("temas", [tema])
        if ativo is not None:
            query = query.eq("ativo", ativo)
        if busca:
            query = query.or_(f"texto.ilike.%{busca}%,autor.ilike.%{busca}%")

        offset = (page - 1) * limit
        query = query.range(offset, offset + limit - 1)

        result = query.execute()

        return {
            "success": True,
            "data": result.data or [],
            "total": result.count or 0,
            "page": page,
            "limit": limit
        }
    except Exception as e:
        logger.error(f"[Frases] List error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/frases")
async def create_frase(data: FraseCreate):
    """Criar nova frase."""
    try:
        supabase = get_supabase_client()
        # Normalizar signos
        normalized_signos = [normalize_signo(s) for s in data.signos]

        result = supabase.table("frases_inspiracao").insert({
            "texto": data.texto,
            "autor": data.autor,
            "fonte": data.fonte,
            "categoria": data.categoria,
            "signos": normalized_signos,
            "temas": data.temas,
            "destaque": data.destaque
        }).execute()

        return {"success": True, "data": result.data}
    except Exception as e:
        logger.error(f"[Frases] Create error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/frases/bulk")
async def create_frases_bulk(frases: List[FraseCreate]):
    """Criar múltiplas frases (para geração IA)."""
    try:
        supabase = get_supabase_client()
        records = [{
            "texto": f.texto,
            "autor": f.autor,
            "fonte": f.fonte,
            "categoria": f.categoria,
            "signos": [normalize_signo(s) for s in f.signos],
            "temas": f.temas,
            "destaque": f.destaque
        } for f in frases]

        result = supabase.table("frases_inspiracao").insert(records).execute()
        return {"success": True, "count": len(result.data or []), "data": result.data}
    except Exception as e:
        logger.error(f"[Frases] Bulk create error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/frases/{frase_id}")
async def update_frase(frase_id: str, data: FraseUpdate):
    """Atualizar frase existente."""
    try:
        supabase = get_supabase_client()
        update_data = {}

        if data.texto is not None:
            update_data["texto"] = data.texto
        if data.autor is not None:
            update_data["autor"] = data.autor
        if data.fonte is not None:
            update_data["fonte"] = data.fonte
        if data.categoria is not None:
            update_data["categoria"] = data.categoria
        if data.signos is not None:
            update_data["signos"] = [normalize_signo(s) for s in data.signos]
        if data.temas is not None:
            update_data["temas"] = data.temas
        if data.ativo is not None:
            update_data["ativo"] = data.ativo
        if data.destaque is not None:
            update_data["destaque"] = data.destaque

        if not update_data:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        result = supabase.table("frases_inspiracao").update(
            update_data
        ).eq("id", frase_id).execute()

        return {"success": True, "data": result.data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Frases] Update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/frases/{frase_id}")
async def delete_frase(frase_id: str):
    """Excluir frase."""
    try:
        supabase = get_supabase_client()
        supabase.table("frases_inspiracao").delete().eq("id", frase_id).execute()
        return {"success": True}
    except Exception as e:
        logger.error(f"[Frases] Delete error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# GERAÇÃO DE FRASES COM IA
# ============================================

GERAR_FRASES_PROMPT = """Você é um curador de frases inspiracionais do VibraEu, plataforma de astrologia cabalística e autoconhecimento.

REGRAS:
1. Cada frase DEVE ser única, profunda e cativante
2. Use linguagem elevada mas acessível
3. Quando for sobre um signo, conecte com a essência arquetípica dele
4. Para citações, use autores reais e verifique a precisão
5. Mantenha frases concisas (máximo 2 linhas)
6. Retorne APENAS o JSON, sem markdown ou explicações

Retorne um array JSON com objetos no formato:
[
  {
    "texto": "A frase aqui",
    "autor": "Nome do Autor" ou null,
    "fonte": "Livro ou Fonte" ou null,
    "temas": ["tema1", "tema2"]
  }
]"""


@router.post("/frases/gerar")
async def gerar_frases(req: GerarFrasesRequest):
    """Gerar frases com IA baseado na categoria, tema e signo."""
    try:
        gateway = LLMGateway.get_instance()

        prompt_parts = [f"Gere {req.quantidade} frases na categoria '{req.categoria}'."]

        if req.signo:
            prompt_parts.append(f"As frases devem ser especificamente para o signo {req.signo.upper()}, conectando com sua essência astrológica cabalística.")
        if req.tema:
            prompt_parts.append(f"Tema central: {req.tema}.")

        prompt_parts.append("Retorne APENAS o array JSON com as frases.")

        prompt = " ".join(prompt_parts)

        result = await gateway.generate(
            prompt=prompt,
            system_prompt=GERAR_FRASES_PROMPT,
            config={
                "provider": "groq",
                "model": "llama-3.3-70b-versatile",
                "fallback_provider": "openai",
                "fallback_model": "gpt-4o-mini",
                "temperature": 0.85,
                "max_tokens": 2000
            }
        )

        # Parse JSON da resposta
        import json
        # Limpar possíveis blocos markdown
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        frases_raw = json.loads(cleaned)

        # Formatar para o padrão esperado
        frases = []
        for f in frases_raw:
            frases.append({
                "texto": f.get("texto", ""),
                "autor": f.get("autor"),
                "fonte": f.get("fonte"),
                "categoria": req.categoria,
                "signos": [normalize_signo(req.signo)] if req.signo else [],
                "temas": f.get("temas", [req.tema] if req.tema else []),
                "destaque": False
            })

        return {"success": True, "frases": frases}

    except json.JSONDecodeError as e:
        logger.error(f"[Frases] JSON parse error: {e} — raw: {result[:200]}")
        raise HTTPException(status_code=500, detail="Erro ao processar resposta da IA")
    except Exception as e:
        logger.error(f"[Frases] Generate error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# ENDPOINTS PÚBLICOS (consumo pelo app)
# ============================================

@router.get("/frases/dia/{user_id}")
async def frases_do_dia(user_id: str):
    """
    Retorna 5 frases do dia personalizadas para o user.
    Filtra pelo MAC do user (sol, lua, ascendente, mc).
    Usa seed baseada na data para manter consistência no mesmo dia.
    Cached por 30min (frases do dia não mudam intra-dia).
    """
    from datetime import date
    
    # Check cache (30min TTL)
    cache_key = f"frases_dia:{user_id}:{date.today().isoformat()}"
    cached = response_cache.get(cache_key)
    if cached:
        return cached
    
    try:
        supabase = get_supabase_client()

        # 1. Buscar signos do user no MAC
        mac_result = supabase.table("mapas_astrais").select(
            "sol_signo, lua_signo, ascendente_signo, mc_signo"
        ).eq("user_id", user_id).maybe_single().execute()

        user_signos = []
        if mac_result.data:
            mac = mac_result.data
            for campo in ["sol_signo", "lua_signo", "ascendente_signo", "mc_signo"]:
                if mac.get(campo):
                    user_signos.append(normalize_signo(mac[campo]))

        # 2. Buscar frases — mix de personalizadas + universais
        frases_personalizadas = []
        if user_signos:
            for signo in user_signos[:3]:
                signo_result = supabase.table("frases_inspiracao").select("*").eq(
                    "ativo", True
                ).contains("signos", [signo]).limit(5).execute()
                frases_personalizadas.extend(signo_result.data or [])

        # Frases universais (sem signo específico / signos vazio)
        universal_result = supabase.table("frases_inspiracao").select("*").eq(
            "ativo", True
        ).eq("signos", "{}").limit(20).execute()
        frases_universais = universal_result.data or []

        # 3. Montar mix: 2-3 personalizadas + 2-3 universais = 5 total
        import random

        seed_str = f"{date.today().isoformat()}_{user_id}"
        seed = hash(seed_str) % (2**32)
        rng = random.Random(seed)

        # Deduplicate
        seen_ids = set()
        personalizadas_unicas = []
        for f in frases_personalizadas:
            if f["id"] not in seen_ids:
                seen_ids.add(f["id"])
                personalizadas_unicas.append(f)

        universais_unicas = []
        for f in frases_universais:
            if f["id"] not in seen_ids:
                seen_ids.add(f["id"])
                universais_unicas.append(f)

        rng.shuffle(personalizadas_unicas)
        rng.shuffle(universais_unicas)

        result_frases = []
        result_frases.extend(personalizadas_unicas[:3])
        remaining = 5 - len(result_frases)
        result_frases.extend(universais_unicas[:remaining])

        if len(result_frases) < 5:
            extra = personalizadas_unicas[3:] + universais_unicas[remaining:]
            result_frases.extend(extra[:5 - len(result_frases)])

        rng.shuffle(result_frases)

        response = {
            "success": True,
            "frases": result_frases[:5],
            "user_signos": list(set(user_signos)),
            "data": date.today().isoformat()
        }
        
        # Cachear por 30min
        response_cache.set(cache_key, response, ttl=1800)
        
        return response

    except Exception as e:
        logger.error(f"[Frases] Frases do dia error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/frases/random")
async def frases_random(
    quantidade: int = Query(5, ge=1, le=20),
    categoria: Optional[str] = None,
    signo: Optional[str] = None,
    tema: Optional[str] = None,
):
    """Retorna frases aleatórias com filtros opcionais. Cache 1min."""
    # Check cache (1min TTL)
    cache_key = f"frases_random:{quantidade}:{categoria}:{signo}:{tema}"
    cached = response_cache.get(cache_key)
    if cached:
        return cached
    
    try:
        supabase = get_supabase_client()
        query = supabase.table("frases_inspiracao").select("*").eq("ativo", True)

        if categoria:
            query = query.eq("categoria", categoria)
        if signo:
            normalized = normalize_signo(signo)
            query = query.contains("signos", [normalized])
        if tema:
            query = query.contains("temas", [tema])

        query = query.limit(quantidade * 3)
        result = query.execute()

        import random
        frases = result.data or []
        random.shuffle(frases)

        response = {
            "success": True,
            "frases": frases[:quantidade],
            "total_disponivel": len(frases)
        }
        
        # Cachear por 1min
        response_cache.set(cache_key, response, ttl=60)
        
        return response

    except Exception as e:
        logger.error(f"[Frases] Random error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
