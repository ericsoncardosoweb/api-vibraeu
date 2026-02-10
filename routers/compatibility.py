"""
Compatibility Analysis Router — Vibra EU
Generates rich astrological compatibility reports using GPT-4.1 mini.
Replaces n8n webhook for compatibility analysis.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from loguru import logger
import json
import re

from services.llm_gateway import LLMGateway
from services.supabase_client import get_supabase_client

router = APIRouter()


# ============================================================================
# Models
# ============================================================================

class CompatibilityRequest(BaseModel):
    teste_id: str
    test_type: str  # amor, amizade, negocios, familia
    responder: Dict[str, Any]
    responder_mac: Dict[str, Any]
    creator: Dict[str, Any]
    creator_mac: Dict[str, Any]
    compatibility: Dict[str, Any]
    response_id: str
    created_at: Optional[str] = None


# ============================================================================
# Prompt de Sinastria
# ============================================================================

SYSTEM_PROMPT = """Você é um astrólogo especializado em sinastria (análise de compatibilidade entre mapas astrais) do aplicativo Vibra Eu.

Sua função é gerar análises de compatibilidade que sejam:
- Matematicamente precisas (cálculos reais, não aleatórios)
- Tecnicamente profundas (análise astrológica real)
- Ricas em insights (incluindo complementaridade de elementos)
- Adaptadas ao tipo de relação
- Engajantes e compartilháveis

Você DEVE retornar APENAS JSON puro, sem markdown code blocks, sem comentários."""


def build_analysis_prompt(data: CompatibilityRequest) -> str:
    """Build the full analysis prompt with MAC data."""
    
    creator_name = data.creator.get("nomeCompleto") or data.creator.get("nome", "Usuário 1")
    responder_name = data.responder.get("nome", "Usuário 2")
    
    return f"""## Entradas para Análise

### 1. Mapa Astral - Usuário 1 (Criador do Teste): {creator_name}
```json
{json.dumps(data.creator_mac, ensure_ascii=False, default=str)}
```

### 2. Mapa Astral - Usuário 2 (Respondente): {responder_name}
```json
{json.dumps(data.responder_mac, ensure_ascii=False, default=str)}
```

### 3. Tipo de Análise: {data.test_type}

---

## METODOLOGIA DE ANÁLISE

### PASSO 1: Mapeamento de Signos

#### Elementos:
- **Fogo:** Áries, Leão, Sagitário → iniciativa, paixão, ação
- **Terra:** Touro, Virgem, Capricórnio → praticidade, estabilidade, materialização
- **Ar:** Gêmeos, Libra, Aquário → comunicação, intelecto, ideias
- **Água:** Câncer, Escorpião, Peixes → emoção, intuição, sensibilidade

#### Modalidades:
- **Cardinal:** Áries, Câncer, Libra, Capricórnio → iniciação, liderança
- **Fixo:** Touro, Leão, Escorpião, Aquário → persistência, estabilidade
- **Mutável:** Gêmeos, Virgem, Sagitário, Peixes → adaptabilidade, flexibilidade

### PASSO 2: Cálculo de Compatibilidade por Aspecto

#### A. Compatibilidade LUNAR (Vida Emocional)
Fórmula de aspectos angulares:
- Mesmo signo (conjunção): 100%
- Mesmo elemento (trígono): 85-90%
- Signos complementares (sextil): 75-80%
- Elementos harmônicos (Fogo-Ar ou Terra-Água): 70-75%
- Quadratura (3 signos): 40-50%
- Oposição (6 signos): 45-55%
- Elementos conflitantes: 30-40%

#### B-D. Mesma fórmula para SOL, MARTE, VÊNUS

#### E. Compatibilidade de ELEMENTOS
Compare distribuições elementares. Identifique complementaridade (carência de um supre excesso do outro = +10-15 pontos).

#### F. Compatibilidade de MODALIDADES
Compare distribuições. Cardinal+Fixo/Mutável = 80-90%. Equilíbrio = 85-95%.

### PASSO 3: Pesos por Tipo

**AMOR:** Lua 25%, Sol 20%, Marte 15%, Vênus 25%, Elementos 10%, Modalidades 5%
**AMIZADE:** Lua 20%, Sol 25%, Marte 15%, Vênus 15%, Elementos 15%, Modalidades 10%
**NEGÓCIOS:** Lua 10%, Sol 25%, Marte 25%, Vênus 10%, Elementos 15%, Modalidades 15%
**FAMÍLIA:** Lua 25%, Sol 25%, Marte 15%, Vênus 15%, Elementos 10%, Modalidades 10%

### PASSO 4: Análise de Complementaridade

Identifique padrões:
1. Carência/Excesso (um supre o que falta no outro): 85-95%
2. Espelhamento (ambos parecidos): 75-85%
3. Desafio Criativo (diferenças produtivas): 60-75%
4. Oposição Complementar (opostos que se atraem): 55-70%
5. Incompatibilidade Real: 30-45%

## Tom por Tipo
- AMOR: Íntimo, emocional, realista. Foco em conexão profunda.
- AMIZADE: Leve, caloroso, autêntico. Foco em cumplicidade.
- NEGÓCIOS: Profissional, estratégico, direto. Foco em sinergia.
- FAMÍLIA: Sensível, acolhedor. Foco em convivência.

## Estrutura JSON de Saída (OBRIGATÓRIA)
```json
{{
  "tipo_analise": "{data.test_type}",
  "usuario1": "{creator_name}",
  "usuario2": "{responder_name}",
  "compatibilidade_total": 78,
  "nivel_compatibilidade": "Alta compatibilidade",
  "aspectos": {{
    "lua": {{
      "porcentagem": 85,
      "analise": "Texto de 3-4 linhas",
      "match_tipo": "harmonico|complementar|desafiador|neutro"
    }},
    "sol": {{
      "porcentagem": 72,
      "analise": "Texto de 3-4 linhas",
      "match_tipo": "harmonico|complementar|desafiador|neutro"
    }},
    "marte": {{
      "porcentagem": 68,
      "analise": "Texto de 3-4 linhas",
      "match_tipo": "harmonico|complementar|desafiador|neutro"
    }},
    "venus": {{
      "porcentagem": 90,
      "analise": "Texto de 3-4 linhas",
      "match_tipo": "harmonico|complementar|desafiador|neutro"
    }},
    "elementos": {{
      "porcentagem": 88,
      "analise": "Texto de 3-4 linhas",
      "match_tipo": "harmonico|complementar|desafiador|neutro"
    }},
    "modalidades": {{
      "porcentagem": 75,
      "analise": "Texto de 3-4 linhas",
      "match_tipo": "harmonico|complementar|desafiador|neutro"
    }}
  }},
  "insight_complementaridade": {{
    "titulo": "Complementaridade Natural",
    "tipo": "carencia_excesso|espelhamento|desafio_criativo|oposicao_complementar|incompatibilidade",
    "descricao": "Texto rico de 5-8 linhas explicando COMO os elementos se complementam."
  }},
  "pontos_fortes": [
    {{
      "aspecto": "Descrição técnica do aspecto",
      "impacto": "alto|medio|baixo",
      "explicacao": "Como isso se manifesta (2-3 linhas)"
    }}
  ],
  "desafios": [
    {{
      "aspecto": "Descrição técnica do aspecto",
      "impacto": "alto|medio|baixo",
      "explicacao": "Como lidar construtivamente (2-3 linhas)"
    }}
  ],
  "recomendacoes": [
    "Recomendação prática 1",
    "Recomendação prática 2",
    "Recomendação prática 3"
  ],
  "frase_sintese": "Uma frase poderosa que captura a essência única desta conexão"
}}
```

**Formato de resposta:** JSON puro, sem markdown code blocks, sem comentários."""


# ============================================================================
# Endpoint
# ============================================================================

@router.post("/analyze")
async def analyze_compatibility(data: CompatibilityRequest):
    """
    Analyze compatibility between two astrological maps.
    Generates rich report via GPT-4.1 mini and updates the database.
    Also handles deduplication — if same test_type exists between same users,
    deletes the older response.
    """
    logger.info(f"[Compatibility] Analyzing {data.test_type} for response {data.response_id}")
    
    try:
        supabase = get_supabase_client()
        
        # ── 1. Deduplicação ──────────────────────────────────────────────
        # Buscar responses anteriores do MESMO teste e tipo (excluindo a atual)
        # que já foram processadas para o mesmo respondente
        try:
            existing = supabase.table("compatibility_responses") \
                .select("id, nome, email") \
                .eq("test_id", data.teste_id) \
                .neq("id", data.response_id) \
                .execute()
            
            if existing.data:
                # Filtrar por mesmo respondente (mesmo email ou mesmo nome + data nascimento)
                responder_email = data.responder.get("email", "").lower().strip()
                responder_nome = data.responder.get("nome", "").lower().strip()
                
                duplicates_to_delete = []
                for resp in existing.data:
                    resp_email = (resp.get("email") or "").lower().strip()
                    resp_nome = (resp.get("nome") or "").lower().strip()
                    
                    # Match por email ou nome exato
                    if (responder_email and resp_email == responder_email) or \
                       (responder_nome and resp_nome == responder_nome):
                        duplicates_to_delete.append(resp["id"])
                
                if duplicates_to_delete:
                    logger.info(f"[Compatibility] Removing {len(duplicates_to_delete)} duplicate(s) for same users")
                    supabase.table("compatibility_responses") \
                        .delete() \
                        .in_("id", duplicates_to_delete) \
                        .execute()
        except Exception as e:
            logger.warning(f"[Compatibility] Dedup check failed (non-blocking): {e}")
        
        # ── 2. Gerar análise via LLM ────────────────────────────────────
        llm = LLMGateway.get_instance()
        prompt = build_analysis_prompt(data)
        
        raw_response = await llm.generate(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            config={
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "temperature": 0.5,
                "max_tokens": 4000
            }
        )
        
        # ── 3. Parsear JSON ──────────────────────────────────────────────
        report = parse_llm_json(raw_response)
        
        if not report:
            logger.error(f"[Compatibility] Failed to parse LLM response for {data.response_id}")
            raise HTTPException(status_code=500, detail="Failed to parse compatibility report")
        
        # Extrair score do report
        new_score = report.get("compatibilidade_total")
        
        logger.info(
            f"[Compatibility] Generated report: score={new_score}, "
            f"level={report.get('nivel_compatibilidade')}"
        )
        
        # ── 4. Atualizar banco ───────────────────────────────────────────
        update_data = {
            "compatibility_report": report
        }
        
        # Atualizar score se o LLM gerou um
        if new_score is not None:
            update_data["compatibility_score"] = new_score
        
        result = supabase.table("compatibility_responses") \
            .update(update_data) \
            .eq("id", data.response_id) \
            .execute()
        
        if not result.data:
            logger.warning(f"[Compatibility] Response {data.response_id} not found for update")
        
        logger.info(f"[Compatibility] ✅ Report saved for response {data.response_id}")
        
        return {
            "success": True,
            "response_id": data.response_id,
            "report": report,
            "score": new_score
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Compatibility] Error analyzing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def parse_llm_json(raw: str) -> dict | None:
    """Parse JSON from LLM response, handling code blocks and extra text."""
    if not raw:
        return None
    
    # Remove markdown code blocks
    cleaned = raw.strip()
    
    # Try extracting from ```json ... ``` blocks
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', cleaned, re.DOTALL)
    if json_match:
        cleaned = json_match.group(1).strip()
    
    # Try finding JSON object directly
    if not cleaned.startswith('{'):
        brace_start = cleaned.find('{')
        if brace_start >= 0:
            cleaned = cleaned[brace_start:]
    
    # Find matching closing brace
    if cleaned.startswith('{'):
        depth = 0
        end_idx = -1
        for i, c in enumerate(cleaned):
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end_idx = i
                    break
        if end_idx > 0:
            cleaned = cleaned[:end_idx + 1]
    
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"[Compatibility] JSON parse error: {e}")
        logger.debug(f"[Compatibility] Raw response (first 500 chars): {raw[:500]}")
        return None
"""Router for compatibility analysis."""
