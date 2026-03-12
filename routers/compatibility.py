"""
Compatibility Analysis Router — Vibra EU
Generates rich astrological compatibility reports using GPT-4.1 mini.
Each test type (amor, amizade, negocios, familia) has individualized prompts.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from loguru import logger
from datetime import datetime
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


class DirectCompatibilityRequest(BaseModel):
    """Request for community-based compatibility (between registered users)."""
    user_a_id: str
    user_b_id: str
    user_a_name: str
    user_b_name: str
    user_a_mac: Dict[str, Any]
    user_b_mac: Dict[str, Any]
    test_type: str
    compatibility_id: Optional[str] = None
    local_score: Optional[int] = None
    local_report: Optional[Dict[str, Any]] = None
    user_a_profile: Optional[Dict[str, Any]] = None
    user_b_profile: Optional[Dict[str, Any]] = None


# ============================================================================
# SYSTEM PROMPT (base)
# ============================================================================

SYSTEM_PROMPT = """Você é um astrólogo especializado em **sinastria** (análise de compatibilidade entre mapas astrais) do aplicativo **Vibra Eu**.

Sua função é gerar análises de compatibilidade que sejam:
- **Matematicamente precisas** (cálculos reais baseados nos aspectos angulares, NÃO aleatórios)
- **Tecnicamente profundas** (análise astrológica real com referências aos signos, elementos, modalidades e o quarteto fundamental)
- **Ricas em insights** (complementaridade de elementos com dados ESPECÍFICOS das distribuições)
- **Personalizadas** (usando nomes das pessoas, idade, contexto quando disponível)
- **Engajantes e compartilháveis** (a pessoa deve querer mostrar para o outro)

REGRAS:
1. Cada análise de aspecto deve ter 3-5 linhas ricas, CITANDO os signos específicos dos dois mapas.
2. O quarteto fundamental (Sol + Ascendente, Lua, Meio do Céu) é a base mais importante da análise.
3. Pontos fortes: 3-5 items. Desafios: 2-4 items. Recomendações: 3-5.
4. A frase_sintese deve ser poética, marcante e compartilhável.
5. Use os NOMES/apelidos das pessoas ao longo da análise.
6. Retorne APENAS JSON puro, sem markdown code blocks, sem comentários."""


# ============================================================================
# Blocos de Prompt por Tipo
# ============================================================================

# -- Base metodológica (compartilhada) --
_METHODOLOGY_BASE = """
## METODOLOGIA DE ANÁLISE

### Mapeamento Astrológico

#### Elementos:
- **Fogo:** Áries, Leão, Sagitário → iniciativa, paixão, ação, coragem
- **Terra:** Touro, Virgem, Capricórnio → praticidade, estabilidade, materialização, segurança
- **Ar:** Gêmeos, Libra, Aquário → comunicação, intelecto, ideias, sociabilidade
- **Água:** Câncer, Escorpião, Peixes → emoção, intuição, sensibilidade, profundidade

#### Modalidades:
- **Cardinal:** Áries, Câncer, Libra, Capricórnio → iniciação, liderança, impulso
- **Fixo:** Touro, Leão, Escorpião, Aquário → persistência, estabilidade, determinação
- **Mutável:** Gêmeos, Virgem, Sagitário, Peixes → adaptabilidade, flexibilidade, versatilidade

#### Polaridades:
- **Yang (ativo):** Fogo + Ar
- **Yin (receptivo):** Terra + Água

### Tabela de Aspectos Angulares (para TODOS os planetas)

| Aspecto Angular | Porcentagem |
|---|---|
| Mesmo signo (conjunção) | 95-100% |
| Mesmo elemento (trígono) | 85-90% |
| Signos complementares (sextil — 2 signos) | 75-80% |
| Elementos harmônicos (Fogo-Ar / Terra-Água) | 70-75% |
| Oposição (6 signos) | 45-55% (pode ser complementar) |
| Quadratura (3 signos) | 40-50% |
| Elementos conflitantes (Fogo-Água / Terra-Ar) | 30-40% |

---

## O QUARTETO FUNDAMENTAL (análise prioritária)

Os 4 pontos mais importantes de qualquer mapa são:
1. **Sol** — Identidade essencial, propósito de vida, como a pessoa BRILHA
2. **Ascendente** — Máscara social, primeira impressão, como os OUTROS a veem
3. **Lua** — Mundo emocional, necessidades internas, como a pessoa SE SENTE
4. **Meio do Céu (MC)** — Vocação, direção de vida, como a pessoa quer ser RECONHECIDA

Na sinastria, cruzar esses 4 pontos entre os dois mapas revela:
- Sol de A vs Sol de B → Compatibilidade de identidade
- Lua de A vs Lua de B → Compatibilidade emocional
- Ascendente de A vs Sol de B → Como B percebe A (e vice-versa)
- MC de A vs MC de B → Alinhamento de propósito e direção de vida

### Como Analisar o Quarteto:

**Convergência Sol-Ascendente entre mapas:**
Se o Sol de um cai no mesmo elemento ou signo do Ascendente do outro, há uma atração natural — a pessoa É aquilo que o outro PROJETA. Isso gera reconhecimento instantâneo.

**Convergência Lua-Lua:**
Luas no mesmo elemento = entendimento emocional profundo sem palavras.
Luas em elementos opostos = cada um nutre o outro de forma que falta internamente.

**MC cruzado:**
MCs compatíveis = mesma ambição e visão de futuro. Fundamental para negócios e relações de longo prazo.

---

## ANÁLISE ELEMENTAR PROFUNDA

Para cada mapa, calcule a distribuição de elementos (% de planetas em cada):
1. Liste todos os planetas e seus signos
2. Classifique cada signo no elemento correspondente
3. Calcule: Fogo X%, Terra Y%, Ar Z%, Água W%

**Depois COMPARE os dois mapas:**
- Onde há CONVERGÊNCIA (ambos fortes no mesmo elemento) → entendimento natural
- Onde há COMPLEMENTARIDADE (forte de um = fraco do outro) → se completam
- Onde há CARÊNCIA MÚTUA (ambos fracos no mesmo) → ponto cego compartilhado
- Onde há EXCESSO MÚTUO (ambos muito fortes no mesmo) → pode saturar

Use porcentagens ESPECÍFICAS na análise:
"Ericson tem 50% de Fogo e apenas 5% de Água, enquanto Rayanna tem 45% de Água e 10% de Fogo — isso cria uma dinâmica onde ele traz a iniciativa e ela a profundidade emocional"
"""

# -- Foco específico por tipo --
_FOCUS_AMOR = """
## FOCO: ANÁLISE ROMÂNTICA (AMOR)

### Aspectos mais relevantes (em ordem de importância):
1. **Vênus-Vênus** — Como demonstram e recebem amor. Compatibilidade de linguagem afetiva.
2. **Lua-Lua** — Segurança emocional juntos. O que cada um precisa para se sentir amado.
3. **Marte-Vênus (cruzado)** — Química sexual e atração magnética. O desejo de um encontra a receptividade do outro.
4. **Sol-Sol** — Respeito mútuo e admiração pela essência do parceiro.
5. **Ascendente-Sol (cruzado)** — Primeira impressão e atração visual/imediata.
6. **MC-MC** — Visão de futuro compartilhada. Construção a longo prazo.

### Pesos:
Lua 25% | Vênus 25% | Sol 15% | Marte 15% | Elementos 10% | Modalidades 5% | Quarteto (bônus contexto)

### Tom de Escrita:
- Íntimo, emocional, mas REALISTA
- Abordar paixão E construção de longo prazo
- Mencionar atração e química quando relevante
- Ser honesto sobre desafios sem destruir a magia
- Usar linguagem que desperte curiosidade ("há uma tensão entre vocês que...")

### Insight viral obrigatório:
Explicar como o mapa de um ATRAI o do outro — usar Marte-Vênus cruzado e Ascendente-Sol.
"""

_FOCUS_AMIZADE = """
## FOCO: ANÁLISE DE AMIZADE

### Aspectos mais relevantes:
1. **Sol-Sol** — Afinidade de identidade. Vocês se "veem" um no outro?
2. **Lua-Lua** — Nível de vulnerabilidade e conforto emocional.
3. **Mercúrio (se disponível)** — Comunicação, humor compartilhado, temas de conversa.
4. **Marte-Marte** — Energia conjunta. Como se divertem, competem ou colaboram.
5. **Ascendente-Ascendente** — Impressão mútua. A "vibe" que emitem juntos.
6. **Elementos cruzados** — Onde um enriquece o mundo do outro.

### Pesos:
Sol 25% | Lua 20% | Marte 15% | Vênus 15% | Elementos 15% | Modalidades 10%

### Tom de Escrita:
- Leve, caloroso, autêntico
- Celebrar as diferenças que enriquecem a amizade
- Esclarecer desafios de convivência e comunicação
- Focar em cumplicidade, apoio mútuo, risadas
- Linguagem descontraída ("são aqueles amigos que...")

### Insight viral obrigatório:
Mostrar o que torna essa amizade ÚNICA — o que um traz que o outro não tem.
"""

_FOCUS_NEGOCIOS = """
## FOCO: ANÁLISE PROFISSIONAL/NEGÓCIOS

### Aspectos mais relevantes:
1. **Sol-Sol** — Liderança: competem ou se complementam?
2. **Marte-Marte** — Energia de execução. Como tomam decisões e lidam com pressão.
3. **MC-MC** — Alinhamento de ambição, visão de carreira e como querem ser reconhecidos profissionalmente.
4. **Saturno (se disponível)** — Disciplina, comprometimento, estrutura.
5. **Elementos (Terra/Ar)** — Praticidade vs inovação. Quem executa, quem idealiza.
6. **Modalidades** — Cardinal (lidera) + Fixo (sustenta) + Mutável (adapta) = sinergia ideal.

### Pesos:
Sol 25% | Marte 25% | Elementos 15% | Modalidades 15% | Lua 10% | Vênus 10%

### Tom de Escrita:
- Profissional, estratégico, direto
- Foco em sinergia, complementaridade de habilidades e resultados
- ROI emocional e prático da parceria
- Usar linguagem de negócios ("a sinergia entre vocês se destaca em...")
- Ser objetivo sobre riscos e como mitigá-los

### Insight viral obrigatório:
Mostrar a SINERGIA profissional — onde as forças de um cobrem fraquezas do outro em contexto de trabalho.
"""

_FOCUS_FAMILIA = """
## FOCO: ANÁLISE FAMILIAR

### Aspectos mais relevantes:
1. **Lua-Lua** — Vínculo emocional fundamental. Como nutrem e cuidam emocionalmente.
2. **Sol-Sol** — Respeito pela individualidade. Choque ou harmonia de personalidades.
3. **Marte-Marte** — Como lidam com conflitos familiares. Convivência sob pressão.
4. **Vênus-Vênus** — Valores compartilhados, tradições, o que importa para ambos.
5. **MC cruzado** — Apoio às ambições do outro. O familiar incentiva ou limita?
6. **Saturno/Modalidades** — Estrutura familiar, responsabilidade, disciplina.

### Pesos:
Lua 25% | Sol 25% | Marte 15% | Vênus 15% | Elementos 10% | Modalidades 10%

### Tom de Escrita:
- Sensível, acolhedor, respeitoso
- Foco em convivência, respeito mútuo e crescimento
- Abordar dinâmicas de poder com delicadeza
- Valorizar o vínculo familiar e o crescimento conjunto
- Linguagem gentil ("a conexão entre vocês tem raízes em...")

### ATENÇÃO SOBRE PERFIL EM FAMÍLIA:
- NÃO usar dados como profissão ou estado civil de forma inapropriada
- Focar em dados astrológicos e no vínculo emocional
- Ser sensível com relações pai/mãe-filho(a)

### Insight viral obrigatório:
Revelar o padrão energético que os conecta como família — o legado astral compartilhado.
"""

_TYPE_FOCUS = {
    "amor": _FOCUS_AMOR,
    "amizade": _FOCUS_AMIZADE,
    "negocios": _FOCUS_NEGOCIOS,
    "familia": _FOCUS_FAMILIA,
}


# ============================================================================
# JSON Output Template
# ============================================================================

def _json_output_schema(test_type: str, name_a: str, name_b: str) -> str:
    return f"""
## Estrutura JSON de Saída (OBRIGATÓRIA)
```json
{{{{
  "tipo_analise": "{test_type}",
  "usuario1": "{name_a}",
  "usuario2": "{name_b}",
  "compatibilidade_total": 78,
  "nivel_compatibilidade": "Alta compatibilidade",
  "quarteto": {{{{
    "sol_ascendente": {{{{
      "descricao": "3-5 linhas sobre como o Sol de um interage com o Ascendente do outro. Citar signos.",
      "convergencia": "alta|media|baixa"
    }}}},
    "lua_lua": {{{{
      "descricao": "3-5 linhas sobre a conexão emocional profunda. Citar elementos e signos.",
      "convergencia": "alta|media|baixa"
    }}}},
    "mc_mc": {{{{
      "descricao": "3-5 linhas sobre alinhamento de propósito e direção. Citar signos.",
      "convergencia": "alta|media|baixa"
    }}}}
  }}}},
  "aspectos": {{{{
    "lua": {{{{
      "porcentagem": 85,
      "analise": "3-5 linhas citando signos, elemento, aspecto angular e manifestação prática",
      "match_tipo": "harmonico|complementar|desafiador|neutro"
    }}}},
    "sol": {{{{
      "porcentagem": 72,
      "analise": "3-5 linhas",
      "match_tipo": "harmonico|complementar|desafiador|neutro"
    }}}},
    "venus": {{{{
      "porcentagem": 90,
      "analise": "3-5 linhas focadas no tipo de relação ({test_type})",
      "match_tipo": "harmonico|complementar|desafiador|neutro"
    }}}},
    "marte": {{{{
      "porcentagem": 68,
      "analise": "3-5 linhas focadas no tipo de relação ({test_type})",
      "match_tipo": "harmonico|complementar|desafiador|neutro"
    }}}},
    "elementos": {{{{
      "porcentagem": 88,
      "analise": "3-5 linhas COM porcentagens específicas de distribuição. Convergência vs complementaridade.",
      "match_tipo": "harmonico|complementar|desafiador|neutro",
      "distribuicao_u1": {{{{"fogo": 40, "terra": 25, "ar": 20, "agua": 15}}}},
      "distribuicao_u2": {{{{"fogo": 15, "terra": 30, "ar": 10, "agua": 45}}}},
      "complementaridade_detectada": true
    }}}},
    "modalidades": {{{{
      "porcentagem": 75,
      "analise": "3-5 linhas sobre como Cardinal/Fixo/Mutável interagem entre os dois",
      "match_tipo": "harmonico|complementar|desafiador|neutro"
    }}}}
  }}}},
  "insight_complementaridade": {{{{
    "titulo": "Título viral (ex: A Chama que Encontrou a Água)",
    "tipo": "carencia_excesso|espelhamento|desafio_criativo|oposicao_complementar|incompatibilidade",
    "descricao": "5-8 linhas usando dados ESPECÍFICOS: porcentagens de elementos, signos do quarteto, como se manifesta no cotidiano. Use os nomes das pessoas. Este é o insight mais compartilhável."
  }}}},
  "pontos_fortes": [
    {{{{
      "aspecto": "Descrição técnica (ex: Lua em Sagitário + Lua em Áries — trígono de fogo)",
      "impacto": "alto",
      "explicacao": "2-3 linhas usando nomes das pessoas"
    }}}},
    {{{{
      "aspecto": "Outro ponto",
      "impacto": "medio",
      "explicacao": "2-3 linhas"
    }}}},
    {{{{
      "aspecto": "Outro ponto",
      "impacto": "alto",
      "explicacao": "2-3 linhas"
    }}}}
  ],
  "desafios": [
    {{{{
      "aspecto": "Descrição técnica",
      "impacto": "medio",
      "explicacao": "2-3 linhas com orientação sobre como lidar"
    }}}},
    {{{{
      "aspecto": "Outro desafio",
      "impacto": "alto",
      "explicacao": "2-3 linhas"
    }}}}
  ],
  "recomendacoes": [
    "Recomendação prática e acionável 1 baseada nos aspectos reais — adaptada ao tipo {test_type}",
    "Recomendação prática 2",
    "Recomendação prática 3"
  ],
  "frase_sintese": "Uma frase poética e poderosa que captura a essência única desta conexão"
}}}}
```

## Checklist de Validação
- Analisei o QUARTETO (Sol+Ascendente, Lua, MC) cruzando os dois mapas?
- Calculei cada aspecto usando aspectos angulares REAIS (não inventei porcentagens)?
- A compatibilidade_total é a média ponderada dos pesos do tipo {test_type}?
- Cada análise tem 3-5 linhas E cita os signos específicos?
- O insight usa % ESPECÍFICAS de distribuição elementar?
- As distribuições elementares estão corretas com base nos planetas reais?
- Há pelo menos 3 pontos fortes e 2 desafios?
- Usei os NOMES/apelidos ao longo das análises?
- O tom está adequado ao tipo {test_type}?
- A frase_sintese é poética e compartilhável?

**Resposta:** JSON puro, sem markdown, sem comentários."""


# ============================================================================
# Profile Helpers
# ============================================================================

def _calculate_age(birth_date_str: str) -> Optional[int]:
    """Calculate age from birth date string."""
    if not birth_date_str:
        return None
    try:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                bd_str = birth_date_str.split("T")[0] if "T" in birth_date_str else birth_date_str
                bd = datetime.strptime(bd_str, fmt)
                today = datetime.now()
                age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
                return age if 0 < age < 120 else None
            except ValueError:
                continue
        return None
    except Exception:
        return None


def _build_profile_context(profile: Dict[str, Any], name: str, test_type: str) -> str:
    """Build contextual profile info for the prompt based on test type."""
    if not profile:
        return f"Nome: {name}"
    
    parts = [f"Como gosta de ser chamado(a): {profile.get('nickname') or name}"]
    
    age = _calculate_age(profile.get("birth_date") or profile.get("dataNascimento", ""))
    if age:
        parts.append(f"Idade: {age} anos")
    
    sexo = profile.get("sexo")
    if sexo and test_type in ("amor", "amizade", "negocios"):
        parts.append(f"Sexo: {sexo}")
    
    profissao = profile.get("profissao") or profile.get("profession")
    if profissao and test_type in ("negocios", "amor", "amizade"):
        parts.append(f"Profissão: {profissao}")
    
    estado_civil = profile.get("estado_civil") or profile.get("estadoCivil") or profile.get("marital_status")
    if estado_civil and test_type == "amor":
        parts.append(f"Estado civil: {estado_civil}")
    
    cidade = profile.get("birth_city")
    if cidade:
        parts.append(f"Cidade natal: {cidade}")
    
    return "\n".join(parts)


# ============================================================================
# Prompt Builder
# ============================================================================

def build_analysis_prompt(data: CompatibilityRequest, profile_a: Dict = None, profile_b: Dict = None) -> str:
    """Build the full analysis prompt with MAC data, profile enrichment, and type-specific focus."""
    
    creator_name = data.creator.get("nomeCompleto") or data.creator.get("nome", "Usuário 1")
    responder_name = data.responder.get("nome", "Usuário 2")
    
    profile_a_ctx = _build_profile_context(profile_a, creator_name, data.test_type) if profile_a else f"Nome: {creator_name}"
    profile_b_ctx = _build_profile_context(profile_b, responder_name, data.test_type) if profile_b else f"Nome: {responder_name}"
    
    # Get type-specific focus
    type_focus = _TYPE_FOCUS.get(data.test_type, _FOCUS_AMIZADE)
    
    # JSON schema
    json_schema = _json_output_schema(data.test_type, creator_name, responder_name)
    
    return f"""## Entradas para Análise

### Perfil — Pessoa 1: {creator_name}
{profile_a_ctx}

Mapa Astral Completo (MAC):
```json
{json.dumps(data.creator_mac, ensure_ascii=False, default=str)}
```

### Perfil — Pessoa 2: {responder_name}
{profile_b_ctx}

Mapa Astral Completo (MAC):
```json
{json.dumps(data.responder_mac, ensure_ascii=False, default=str)}
```

### Tipo de Análise: {data.test_type.upper()}

---

{_METHODOLOGY_BASE}

{type_focus}

---

{json_schema}"""


# ============================================================================
# Endpoint: Análise via token público
# ============================================================================

@router.post("/analyze")
async def analyze_compatibility(data: CompatibilityRequest):
    """
    Analyze compatibility between two astrological maps.
    Generates rich report via GPT-4.1 mini and updates the database.
    """
    logger.info(f"[Compatibility] Analyzing {data.test_type} for response {data.response_id}")
    
    try:
        supabase = get_supabase_client()
        
        # ── 1. Deduplicação ──────────────────────────────────────────────
        try:
            existing = supabase.table("compatibility_responses") \
                .select("id, nome, email") \
                .eq("test_id", data.teste_id) \
                .neq("id", data.response_id) \
                .execute()
            
            if existing.data:
                responder_email = data.responder.get("email", "").lower().strip()
                responder_nome = data.responder.get("nome", "").lower().strip()
                
                duplicates_to_delete = []
                for resp in existing.data:
                    resp_email = (resp.get("email") or "").lower().strip()
                    resp_nome = (resp.get("nome") or "").lower().strip()
                    
                    if (responder_email and resp_email == responder_email) or \
                       (responder_nome and resp_nome == responder_nome):
                        duplicates_to_delete.append(resp["id"])
                
                if duplicates_to_delete:
                    logger.info(f"[Compatibility] Removing {len(duplicates_to_delete)} duplicate(s)")
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
                "max_tokens": 5000
            }
        )
        
        # ── 3. Parsear JSON ──────────────────────────────────────────────
        report = parse_llm_json(raw_response)
        
        if not report:
            logger.error(f"[Compatibility] Failed to parse LLM response for {data.response_id}")
            raise HTTPException(status_code=500, detail="Failed to parse compatibility report")
        
        new_score = report.get("compatibilidade_total")
        
        logger.info(
            f"[Compatibility] Generated report: score={new_score}, "
            f"level={report.get('nivel_compatibilidade')}"
        )
        
        # ── 4. Atualizar banco ───────────────────────────────────────────
        update_data = {"compatibility_report": report}
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


# ============================================================================
# Endpoint: Análise direta entre usuários da comunidade
# ============================================================================

def _fetch_user_profile(supabase, user_id: str) -> Dict[str, Any]:
    """Fetch user profile data from Supabase for prompt enrichment."""
    try:
        result = supabase.table("profiles") \
            .select("name, nickname, sexo, profissao, estado_civil, birth_date, birth_city") \
            .eq("id", user_id) \
            .maybe_single() \
            .execute()
        return result.data or {}
    except Exception as e:
        logger.warning(f"[Compatibility] Failed to fetch profile {user_id}: {e}")
        return {}


@router.post("/analyze-direct")
async def analyze_direct_compatibility(data: DirectCompatibilityRequest):
    """
    Analyze compatibility between two registered users (community flow).
    Same rich GPT-4.1 analysis with type-specific prompts.
    Fetches profiles from DB for prompt enrichment.
    """
    logger.info(
        f"[Compatibility/Direct] Analyzing {data.test_type} between "
        f"{data.user_a_name} and {data.user_b_name}"
    )
    
    try:
        supabase = get_supabase_client()
        
        # ── 1. Buscar perfis ────────────────────────────────────────────
        profile_a = data.user_a_profile or _fetch_user_profile(supabase, data.user_a_id)
        profile_b = data.user_b_profile or _fetch_user_profile(supabase, data.user_b_id)
        
        logger.info(
            f"[Compatibility/Direct] Profile A: {profile_a.get('nickname', 'N/A')}, "
            f"Profile B: {profile_b.get('nickname', 'N/A')}"
        )
        
        # ── 2. Montar request ───────────────────────────────────────────
        compat_request = CompatibilityRequest(
            teste_id=data.compatibility_id or "direct",
            test_type=data.test_type,
            responder={
                "nome": profile_b.get("nickname") or data.user_b_name,
            },
            responder_mac=data.user_b_mac,
            creator={
                "user_id": data.user_a_id,
                "nome": profile_a.get("nickname") or data.user_a_name,
                "nomeCompleto": profile_a.get("name") or data.user_a_name,
            },
            creator_mac=data.user_a_mac,
            compatibility={
                "score": data.local_score,
                "report": data.local_report,
            },
            response_id=data.compatibility_id or "direct",
        )
        
        # ── 3. Gerar análise via LLM (prompt individualizado por tipo) ──
        llm = LLMGateway.get_instance()
        prompt = build_analysis_prompt(compat_request, profile_a=profile_a, profile_b=profile_b)
        
        raw_response = await llm.generate(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            config={
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "temperature": 0.5,
                "max_tokens": 5000
            }
        )
        
        # ── 4. Parsear JSON ──────────────────────────────────────────────
        report = parse_llm_json(raw_response)
        
        if not report:
            logger.error("[Compatibility/Direct] Failed to parse LLM response")
            raise HTTPException(status_code=500, detail="Failed to parse compatibility report")
        
        new_score = report.get("compatibilidade_total")
        
        logger.info(
            f"[Compatibility/Direct] Generated: score={new_score}, "
            f"level={report.get('nivel_compatibilidade')}"
        )
        
        # ── 5. Atualizar community_compatibility ─────────────────────────
        if data.compatibility_id:
            try:
                update_data = {
                    "report": report,
                    "ai_enriched": True,
                }
                if new_score is not None:
                    update_data["score"] = new_score
                
                result = supabase.table("community_compatibility") \
                    .update(update_data) \
                    .eq("id", data.compatibility_id) \
                    .execute()
                
                if result.data:
                    logger.info(f"[Compatibility/Direct] ✅ Report saved for {data.compatibility_id}")
                else:
                    logger.warning(f"[Compatibility/Direct] Record {data.compatibility_id} not found")
            except Exception as db_err:
                logger.warning(f"[Compatibility/Direct] DB update failed: {db_err}")
        
        return {
            "success": True,
            "compatibility_id": data.compatibility_id,
            "report": report,
            "score": new_score
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Compatibility/Direct] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Helpers
# ============================================================================

def parse_llm_json(raw: str) -> dict | None:
    """Parse JSON from LLM response, handling code blocks and extra text."""
    if not raw:
        return None
    
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
        logger.debug(f"[Compatibility] Raw (first 500): {raw[:500]}")
        return None
