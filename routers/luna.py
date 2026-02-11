"""
Router para insights personalizados da Luna.
Endpoints: POST /luna/insight

Suporta 3 ferramentas: roda_vida, perfil_comportamental, diario
Cada ferramenta tem prompts e configurações específicas.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from loguru import logger

from services.llm_gateway import LLMGateway
from services.supabase_client import get_supabase_client

router = APIRouter()


# =============================================
# MODELS
# =============================================

class LunaInsightRequest(BaseModel):
    """Requisição de insight da Luna."""
    user_id: str
    tool_key: str  # 'roda_vida' | 'perfil_comportamental' | 'diario'
    profile: Optional[Dict[str, Any]] = None
    mac: Optional[Dict[str, Any]] = None
    tool_data: Optional[Dict[str, Any]] = None
    entries: Optional[List[Dict[str, Any]]] = None  # Para diário
    period_days: Optional[int] = None
    periodo_label: Optional[str] = None
    assessment_id: Optional[str] = None
    roda_vida: Optional[Dict[str, Any]] = None  # Para roda da vida


class LunaInsightResponse(BaseModel):
    """Resposta do insight."""
    success: bool
    relatorio: Optional[str] = None
    frase: Optional[str] = None
    mode: str = "sync"
    error: Optional[str] = None


# =============================================
# SISTEMA DE PROMPTS POR FERRAMENTA
# =============================================

LUNA_SYSTEM_PROMPT = """Você é Luna, uma assistente de autoconhecimento do app Vibra Eu, especialista em astrologia cabalística e desenvolvimento pessoal.

Características do seu estilo:
- Acolhedora e empática, mas direta
- Usa linguagem simples mas profunda
- Conecta padrões emocionais com aspectos astrológicos quando relevante
- Foca em insights práticos e acionáveis
- Termina com uma mensagem motivacional personalizada

IMPORTANTE: Retorne sua análise em formato HTML usando tags <h3>, <p>, <ul>, <li>, <strong>, <blockquote>.
Sempre se refira ao usuário pelo nome quando disponível.
NÃO use markdown. Use APENAS HTML."""


def _build_mac_context(mac: Optional[Dict]) -> str:
    """Monta contexto astrológico se MAC disponível."""
    if not mac:
        return ""
    
    parts = []
    if mac.get('signo_solar') or mac.get('sun_sign'):
        parts.append(f"Signo Solar: {mac.get('signo_solar') or mac.get('sun_sign')}")
    if mac.get('signo_lunar') or mac.get('moon_sign'):
        parts.append(f"Lua em: {mac.get('signo_lunar') or mac.get('moon_sign')}")
    if mac.get('ascendente') or mac.get('rising_sign'):
        parts.append(f"Ascendente: {mac.get('ascendente') or mac.get('rising_sign')}")
    if mac.get('ano_pessoal'):
        parts.append(f"Ano Pessoal: {mac.get('ano_pessoal')}")
    
    if parts:
        return "\n\nDados astrológicos do usuário:\n" + "\n".join(f"- {p}" for p in parts)
    return ""


def _build_prompt_roda_vida(req: LunaInsightRequest) -> str:
    """Prompt para Roda da Vida."""
    nome = req.profile.get('nome', '') if req.profile else 'o usuário'
    roda = req.roda_vida or req.tool_data or {}
    
    # Extrair scores
    scores_text = ""
    if isinstance(roda, dict):
        # Pode vir como {area: score} ou como objeto com campo 'scores'
        scores = roda.get('scores', roda)
        if isinstance(scores, dict):
            scores_text = "\n".join(f"- {area}: {score}/10" for area, score in scores.items() 
                                    if isinstance(score, (int, float)))
    
    mac_ctx = _build_mac_context(req.mac)
    
    return f"""Analise a Roda da Vida de {nome} e gere um relatório completo de insights.

Pontuações por área da vida:
{scores_text}

{mac_ctx}

Gere um relatório em HTML com:
1. <h3>Visão Geral</h3> — Resumo do equilíbrio geral da roda
2. <h3>Pontos Fortes</h3> — Áreas com maior pontuação e como aproveitá-las
3. <h3>Áreas de Atenção</h3> — Áreas com menor pontuação e estratégias para melhorar
4. <h3>Conexões entre Áreas</h3> — Como as áreas se influenciam mutuamente
5. <h3>Plano de Ação</h3> — 3-5 ações práticas priorizadas
6. <blockquote><p><strong>Frase de impacto motivacional</strong></p></blockquote>

Seja específico com base nos scores fornecidos. Não faça análises genéricas."""


def _build_prompt_perfil(req: LunaInsightRequest) -> str:
    """Prompt para Perfil Comportamental."""
    nome = req.profile.get('nome', '') if req.profile else 'o usuário'
    tool = req.tool_data or {}
    mac_ctx = _build_mac_context(req.mac)
    
    pontuacoes = ""
    for animal in ['aguia', 'gato', 'lobo', 'tubarao']:
        score = tool.get(f'pontuacao_{animal}', 0)
        if score:
            pontuacoes += f"- {animal.title()}: {score}\n"
    
    predominante = tool.get('perfil_predominante', 'não identificado')
    
    return f"""Analise o Perfil Comportamental de {nome} e gere um relatório avançado.

Modelo: Teste dos 4 Animais (Águia, Gato, Lobo, Tubarão)
Perfil Predominante: {predominante}

Pontuações:
{pontuacoes}

{mac_ctx}

Gere um relatório completo em HTML com:
1. <h3>Seu Perfil Dominante</h3> — Análise do perfil predominante e suas características
2. <h3>Combinação Comportamental</h3> — Como os perfis secundários influenciam
3. <h3>Pontos Fortes</h3> — Strengths baseados no mix de perfis
4. <h3>Pontos de Desenvolvimento</h3> — Áreas para crescer
5. <h3>Estratégias Práticas</h3> — Como aplicar esse autoconhecimento no dia a dia
6. <blockquote><p><strong>Frase motivacional personalizada</strong></p></blockquote>

Conecte com aspectos astrológicos se disponíveis."""


def _fetch_entries_from_supabase(user_id: str, period_days: int) -> list:
    """Busca entries do diário diretamente do Supabase como fallback."""
    try:
        from datetime import datetime, timedelta
        supabase = get_supabase_client()
        
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=period_days)).strftime('%Y-%m-%d')
        
        result = supabase.table('daily_entries') \
            .select('*') \
            .eq('user_id', user_id) \
            .gte('entry_date', start_date) \
            .lte('entry_date', end_date) \
            .order('entry_date', desc=False) \
            .execute()
        
        if result.data:
            logger.info(f"[Luna] Fallback Supabase: {len(result.data)} entries encontradas para user={user_id}")
            return result.data
        
        return []
    except Exception as e:
        logger.error(f"[Luna] Erro ao buscar entries do Supabase: {e}")
        return []


def _build_prompt_diario(req: LunaInsightRequest) -> str:
    """Prompt para Diário de Bordo."""
    nome = req.profile.get('nome', '') if req.profile else 'o usuário'
    
    # Extrair entries — corrigir precedência do operador
    entries = None
    if req.entries and len(req.entries) > 0:
        entries = req.entries
    elif req.tool_data and isinstance(req.tool_data, dict):
        entries = req.tool_data.get('entries', [])
    
    # Fallback: buscar direto do Supabase se entries veio vazio
    if not entries or len(entries) == 0:
        logger.warning(f"[Luna] Diário: entries vazio no payload, buscando do Supabase para user={req.user_id}")
        entries = _fetch_entries_from_supabase(req.user_id, req.period_days or 7)
    
    logger.info(f"[Luna] Diário: {len(entries)} entries para processar (user={req.user_id})")
    
    period = req.period_days or 7
    periodo_label = req.periodo_label or ('última semana' if period == 7 else f'últimos {period} dias')
    mac_ctx = _build_mac_context(req.mac)
    
    # Formato das entries para a IA
    import json
    entries_formatted = []
    for entry in entries[:50]:  # Limitar para evitar payload gigante
        entries_formatted.append({
            'data': entry.get('entry_date', entry.get('data', '')),
            'humor': entry.get('mood_label', entry.get('humor', f"Nível {entry.get('mood', '?')}")),
            'nivelHumor': entry.get('mood', entry.get('nivelHumor', 0)),
            'sentimentos': entry.get('emotions', entry.get('sentimentos', [])),
            'areasVida': entry.get('factors', entry.get('areasVida', [])),
            'notas': entry.get('notes', entry.get('notas', ''))
        })
    
    logger.info(f"[Luna] Diário: {len(entries_formatted)} entries formatadas. Amostra: {entries_formatted[0] if entries_formatted else 'VAZIO'}")
    
    entries_text = json.dumps(entries_formatted, ensure_ascii=False, indent=2)
    
    return f"""Analise os registros do diário de bordo de {nome} da {periodo_label} e gere um relatório de insights.

REGISTROS DO PERÍODO ({len(entries_formatted)} registros em {period} dias):
{entries_text}

{mac_ctx}

Gere um relatório em HTML com:
1. <h3>Resumo Emocional do Período</h3> — Visão geral de como foi o período emocionalmente
2. <h3>Sentimentos Predominantes</h3> — Quais sentimentos foram mais presentes e o que isso revela
3. <h3>Áreas da Vida que Mais Influenciaram</h3> — Análise das áreas (trabalho, saúde, etc.) que mais impactaram
4. <h3>Padrões Identificados</h3> — Ciclos, tendências e correlações nos dados
5. <h3>Recomendações Personalizadas</h3> — 3-5 sugestões práticas baseadas na análise
6. <blockquote><p><strong>Mensagem motivacional personalizada</strong></p></blockquote>

Seja empático e conecte padrões que {nome} pode não ter notado."""


PROMPT_BUILDERS = {
    'roda_vida': _build_prompt_roda_vida,
    'perfil_comportamental': _build_prompt_perfil,
    'diario': _build_prompt_diario,
}


# =============================================
# ENDPOINT
# =============================================

@router.post("/insight", response_model=LunaInsightResponse)
async def generate_luna_insight(request: LunaInsightRequest):
    """
    Gera um insight personalizado da Luna.
    
    Usa LLM Gateway com fallback automático (Groq → OpenAI → Gemini).
    Retorna HTML formatado pronto para exibição.
    """
    
    # Validar tool_key
    if request.tool_key not in PROMPT_BUILDERS:
        raise HTTPException(
            status_code=400, 
            detail=f"tool_key inválido: '{request.tool_key}'. Use: {list(PROMPT_BUILDERS.keys())}"
        )
    
    try:
        logger.info(f"[Luna] Gerando insight para tool={request.tool_key}, user={request.user_id}")
        
        # Log detalhado para diário
        if request.tool_key == 'diario':
            entries_count = len(request.entries) if request.entries else 0
            logger.info(f"[Luna] Diário payload: entries={entries_count}, period_days={request.period_days}, tool_data={'sim' if request.tool_data else 'não'}")
        
        # 1. Montar prompt
        prompt_builder = PROMPT_BUILDERS[request.tool_key]
        user_prompt = prompt_builder(request)
        
        # 2. Configurar LLM
        llm = LLMGateway.get_instance()
        
        llm_config = {
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "temperature": 0.7,
            "max_tokens": 4000,
            "fallback_provider": "groq",
            "fallback_model": "llama-3.3-70b-versatile"
        }
        
        # 3. Gerar insight
        result = await llm.generate(
            prompt=user_prompt,
            config=llm_config,
            system_prompt=LUNA_SYSTEM_PROMPT
        )
        
        if not result or len(result.strip()) < 50:
            raise ValueError("Resposta da IA muito curta ou vazia")
        
        logger.info(f"[Luna] ✅ Insight gerado: {len(result)} chars para tool={request.tool_key}")
        
        # 4. Extrair frase de impacto se existir no blockquote
        frase = ""
        import re
        blockquote_match = re.search(
            r'<blockquote[^>]*>\s*<p[^>]*>\s*<strong[^>]*>(.*?)</strong>\s*</p>\s*</blockquote>',
            result, re.DOTALL | re.IGNORECASE
        )
        if blockquote_match:
            frase = blockquote_match.group(1).strip()
        
        return LunaInsightResponse(
            success=True,
            relatorio=result,
            frase=frase,
            mode="sync"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Luna] ❌ Erro ao gerar insight: {e}")
        
        # Mensagem de erro amigável
        error_msg = "Erro ao gerar insight. Tente novamente."
        if "rate_limit" in str(e).lower() or "429" in str(e):
            error_msg = "Limite de requisições excedido. Aguarde alguns minutos."
        elif "timeout" in str(e).lower():
            error_msg = "O serviço demorou muito para responder. Tente novamente."
        
        return LunaInsightResponse(
            success=False,
            error=error_msg,
            mode="sync"
        )


# =============================================
# GERAÇÃO DE BIO PARA COMUNIDADE
# =============================================

class GenerateBioRequest(BaseModel):
    """Requisição de geração de bio."""
    user_id: str
    tom: str = "poder"  # poder | amizades | negocios | conexoes | love


class GenerateBioResponse(BaseModel):
    """Resposta com opções de bio."""
    success: bool
    bios: Optional[List[str]] = None
    error: Optional[str] = None


TONS_BIO = {
    "poder": "Transmita força interior, autoridade natural e presença magnética. Frases que mostrem autoconfiança e determinação.",
    "amizades": "Transmita abertura, calor humano, receptividade e energia social. Frases que convidem conexão e acolhimento.",
    "negocios": "Transmita profissionalismo, visão estratégica e credibilidade. Frases que mostrem competência e ambição saudável.",
    "conexoes": "Transmita profundidade, busca por relações autênticas e autoconhecimento. Frases que mostrem sensibilidade e maturidade.",
    "love": "Transmita romantismo sutil, magnetismo e disponibilidade emocional. Frases que mostrem abertura para o amor e sensualidade."
}

VARIACOES_ESTILO = [
    "Use uma metáfora cósmica ou astrológica sutil.",
    "Use um tom poético e filosófico.",
    "Use humor inteligente e leveza.",
    "Use energia e dinamismo, estilo urbano contemporâneo.",
    "Use uma frase impactante e direta, estilo manifesto pessoal."
]


@router.post("/generate-bio", response_model=GenerateBioResponse)
async def generate_bio(request: GenerateBioRequest):
    """
    Gera 5 opções criativas de bio para perfil na comunidade.
    Usa dados do perfil + MAC para personalização profunda.
    """
    tom = request.tom.lower().strip()
    if tom not in TONS_BIO:
        tom = "poder"
    
    try:
        supabase = get_supabase_client()
        
        # 1. Buscar perfil do usuário
        profile_result = supabase.table("profiles") \
            .select("nome, nickname, sexo, profissao, estado_civil, tem_filhos, data_nascimento") \
            .eq("id", request.user_id) \
            .maybeSingle() \
            .execute()
        
        profile = profile_result.data or {}
        
        # 2. Buscar MAC
        mac_result = supabase.table("mapas_astrais") \
            .select("sol_signo, lua_signo, ascendente_signo, mc_signo") \
            .eq("user_id", request.user_id) \
            .maybeSingle() \
            .execute()
        
        mac = mac_result.data or {}
        
        # 3. Calcular idade
        idade_info = ""
        if profile.get("data_nascimento"):
            from datetime import datetime
            try:
                nasc = datetime.strptime(profile["data_nascimento"], "%Y-%m-%d")
                idade = (datetime.now() - nasc).days // 365
                if idade < 25:
                    idade_info = f"Pessoa jovem ({idade} anos) — use linguagem mais atual e energética."
                elif idade < 35:
                    idade_info = f"Adulto jovem ({idade} anos) — equilibre modernidade com maturidade."
                elif idade < 50:
                    idade_info = f"Adulto ({idade} anos) — use tom confiante e sofisticado."
                else:
                    idade_info = f"Pessoa madura ({idade} anos) — use tom sábio e elegante."
            except Exception:
                pass
        
        # 4. Montar contexto do perfil
        nome = profile.get("nickname") or (profile.get("nome", "").split(" ")[0] if profile.get("nome") else "")
        sexo = profile.get("sexo", "")
        profissao = profile.get("profissao", "")
        estado_civil = profile.get("estado_civil", "")
        tem_filhos = profile.get("tem_filhos", "")
        
        genero_ref = "feminino" if sexo == "Feminino" else "masculino" if sexo == "Masculino" else "neutro"
        
        ctx_pessoal = []
        if estado_civil:
            ctx_pessoal.append(f"Estado civil: {estado_civil}")
        if tem_filhos:
            ctx_pessoal.append(f"Tem filhos: {'Sim' if tem_filhos == 'sim' else 'Não'}")
        if profissao:
            ctx_pessoal.append(f"Profissão: {profissao}")
        
        ctx_astral = []
        if mac.get("sol_signo"):
            ctx_astral.append(f"Sol em {mac['sol_signo']}")
        if mac.get("lua_signo"):
            ctx_astral.append(f"Lua em {mac['lua_signo']}")
        if mac.get("ascendente_signo"):
            ctx_astral.append(f"Ascendente em {mac['ascendente_signo']}")
        
        import json
        
        # 5. Montar prompt
        prompt = f"""Gere EXATAMENTE 5 opções de bio para o perfil na comunidade de {nome or 'esta pessoa'}.

CONTEXTO DO USUÁRIO:
- Nome: {nome or 'não informado'}
- Gênero: {genero_ref}
{chr(10).join(f'- {c}' for c in ctx_pessoal) if ctx_pessoal else '- Sem dados pessoais adicionais'}

MAPA ASTRAL:
{chr(10).join(f'- {c}' for c in ctx_astral) if ctx_astral else '- Sem dados astrológicos'}

{idade_info}

TOM DESEJADO: {TONS_BIO[tom]}

REGRAS CRÍTICAS:
1. Cada bio deve ter NO MÁXIMO 200 caracteres
2. Use 1-2 emojis estratégicos por bio (no início ou final)
3. NUNCA mencione dados óbvios como nome ou idade
4. Foque no que AGREGA: essência, energia, propósito
5. Se a pessoa é solteira e jovem, capture essa vibe. Se é casada com filhos, capture essa outra realidade
6. Integre sutilmente a energia do signo solar quando fizer sentido, SEM ser literal ("sou do signo X")
7. Cada bio deve ter um ESTILO DIFERENTE de escrita:
   - Bio 1: {VARIACOES_ESTILO[0]}
   - Bio 2: {VARIACOES_ESTILO[1]}
   - Bio 3: {VARIACOES_ESTILO[2]}
   - Bio 4: {VARIACOES_ESTILO[3]}
   - Bio 5: {VARIACOES_ESTILO[4]}
8. A profissão pode ser mencionada de forma criativa em NO MÁXIMO 2 das 5 opções
9. Cada bio deve funcionar sozinha como uma mini-apresentação impactante

Retorne APENAS um JSON válido no formato:
{{"bios": ["bio1", "bio2", "bio3", "bio4", "bio5"]}}

Sem explicações, sem markdown, somente o JSON."""

        # 6. Chamar LLM
        llm = LLMGateway.get_instance()
        
        result = await llm.generate(
            prompt=prompt,
            config={
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "temperature": 0.9,
                "max_tokens": 1500,
                "fallback_provider": "groq",
                "fallback_model": "llama-3.3-70b-versatile"
            },
            system_prompt="Você é um copywriter especialista em social media e personal branding. Gera textos de bio curtos, criativos e impactantes. Responda APENAS com o JSON solicitado, sem explicações adicionais."
        )
        
        if not result:
            raise ValueError("Resposta vazia da IA")
        
        # 7. Parsear JSON da resposta
        # Limpar possível markdown
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
        
        parsed = json.loads(cleaned)
        bios = parsed.get("bios", [])
        
        if not bios or len(bios) < 3:
            raise ValueError(f"Resposta inválida: esperava 5 bios, recebeu {len(bios)}")
        
        # Truncar bios que ultrapassem 300 chars (safety)
        bios = [b.strip()[:300] for b in bios[:5]]
        
        logger.info(f"[Luna] ✅ Bio gerada para user={request.user_id}, tom={tom}, {len(bios)} opções")
        
        return GenerateBioResponse(success=True, bios=bios)
        
    except json.JSONDecodeError as e:
        logger.error(f"[Luna] Erro ao parsear JSON da bio: {e}")
        return GenerateBioResponse(success=False, error="Erro ao processar resposta da IA. Tente novamente.")
    except Exception as e:
        logger.error(f"[Luna] ❌ Erro ao gerar bio: {e}")
        return GenerateBioResponse(success=False, error="Erro ao gerar bio. Tente novamente.")

