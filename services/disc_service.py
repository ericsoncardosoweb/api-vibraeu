"""
DISC Service — Geração dos insights DISC via IA.
Relatórios: Interferência, Sombra, Potência.

Lógica:
1. Busca dados complementares (MAC, perfil comportamental) do usuário
2. Gera 3 insights sequencialmente via LLM
3. Salva cada insight imediatamente (polling friendly)
4. Marca como 'available' ao final

Os 3 insights:
- Interferência Destrutiva: DISC vs MAC — onde o comportamento interfere na essência
- Sombra Comportamental: medos inconscientes e padrões destrutivos
- Ajuste Fino da Potência: como usar DISC e MAC juntos para potencializar
"""

from datetime import datetime
from typing import Optional, Dict, Any
from loguru import logger
import json

from services.supabase_client import get_supabase_client
from services.llm_gateway import LLMGateway


# ============================================================================
# Mapeamentos
# ============================================================================

PERFIS_DISC = {
    "d": {"nome": "Dominância", "letra": "D", "medo": "perder o controle", "motivacao": "resultados e desafios"},
    "i": {"nome": "Influência", "letra": "I", "medo": "rejeição social", "motivacao": "reconhecimento e conexão"},
    "s": {"nome": "Estabilidade", "letra": "S", "medo": "mudanças bruscas", "motivacao": "segurança e harmonia"},
    "c": {"nome": "Conformidade", "letra": "C", "medo": "estar errado", "motivacao": "precisão e qualidade"},
}

SIGNOS = {
    "Ari": "Áries", "Tau": "Touro", "Gem": "Gêmeos", "Can": "Câncer",
    "Leo": "Leão", "Vir": "Virgem", "Lib": "Libra", "Sco": "Escorpião",
    "Sag": "Sagitário", "Cap": "Capricórnio", "Aqu": "Aquário", "Pis": "Peixes"
}

PLANETAS = {
    "Sun": "Sol", "Moon": "Lua", "Mercury": "Mercúrio",
    "Venus": "Vênus", "Mars": "Marte", "Jupiter": "Júpiter",
    "Saturn": "Saturno", "Uranus": "Urano", "Neptune": "Netuno",
    "Pluto": "Plutão", "Chiron": "Quíron"
}


# ============================================================================
# PROMPTS DOS 3 INSIGHTS
# ============================================================================

INTERFERENCIA_PROMPT = """Você é Luna, a inteligência simbólica do Vibra EU. Você cruza dados do DISC com o Mapa Astral Cabalístico (MAC) do usuário para gerar análises que revelam tensões profundas.

## DADOS DO DISC
- Perfil predominante: {perfil_predominante} ({desc_predominante})
- Perfil secundário: {perfil_secundario} ({desc_secundario})
- Distribuição: D={pct_d}%, I={pct_i}%, S={pct_s}%, C={pct_c}%
- Medo central (DISC): {medo_central}
- Motivação central (DISC): {motivacao_central}

## DADOS DO MAC (Mapa Astral Cabalístico)
{mac_resumo}

## SUA TAREFA: DIAGNÓSTICO DE INTERFERÊNCIA DESTRUTIVA

Analise onde o comportamento DISC do usuário INTERFERE e SABOTA a expressão natural da sua essência astrológica.

Foque em:
1. **Onde o DISC contradiz o MAC**: Ex: perfil D (impaciente, direto) com Lua em Peixes (sensível, receptivo) — o comportamento reprime a sensibilidade emocional inata
2. **Padrões de auto-sabotagem**: Como o estilo comportamental cria loops de estresse
3. **O custo energético**: Quanto energia o usuário gasta mantendo o padrão DISC quando ele conflita com a essência
4. **O gatilho inconsciente**: O que dispara o padrão destrutivo

Escreva em tom profundo, direto e revelador. Use metáforas quando apropriado. O texto deve ter entre 4-5 parágrafos densos.

Retorne um JSON com esta estrutura exata:
{{
    "report": "<div class='insight-content'>CONTEÚDO HTML com <p>, <strong>, <em> — sem <h1> a <h3>, sem markdown</div>",
    "titulo": "Título curto e impactante (max 8 palavras)",
    "frase_chave": "Uma frase de alto impacto que resume a interferência principal",
    "nivel_interferencia": "Alto|Médio|Baixo",
    "ponto_critico": "O ponto exato onde DISC e MAC mais conflitam"
}}"""

SOMBRA_PROMPT = """Você é Luna, a inteligência simbólica do Vibra EU. Você analisa a sombra comportamental — os medos inconscientes que dirigem o padrão DISC do usuário.

## DADOS DO DISC
- Perfil predominante: {perfil_predominante} ({desc_predominante})
- Perfil secundário: {perfil_secundario} ({desc_secundario})
- Distribuição: D={pct_d}%, I={pct_i}%, S={pct_s}%, C={pct_c}%
- Medo central (DISC): {medo_central}
- O que MENOS representa o usuário: {perfil_mais_baixo} ({desc_mais_baixo})

## DADOS DO MAC (Mapa Astral Cabalístico)
{mac_resumo}

## SUA TAREFA: ANÁLISE DA SOMBRA COMPORTAMENTAL

A sombra é o que o usuário EVITA ser. No DISC, o perfil com menor pontuação revela o que o usuário rejeita em si mesmo. Combinado com o MAC, podemos revelar a raiz profunda.

Analise:
1. **O que o usuário rejeita**: O perfil mais baixo no DISC como espelho do que é temido
2. **A armadura**: Como o perfil predominante funciona como defesa contra a vulnerabilidade
3. **A herança astral da sombra**: O que no MAC explica essa rejeição (ex: Saturno, Plutão, casa 12)
4. **O padrão repetitivo**: Como esse medo gera ciclos na vida prática — relacionamentos, trabalho, decisões
5. **O custo escondido**: O que o usuário sacrifica ao evitar essa dimensão

Escreva de forma profunda, psicológica e reveladora. O texto deve ser denso, com 4-5 parágrafos.

Retorne um JSON com esta estrutura exata:
{{
    "report": "<div class='insight-content'>CONTEÚDO HTML com <p>, <strong>, <em> — sem <h1> a <h3>, sem markdown</div>",
    "titulo": "Título curto e impactante (max 8 palavras)",
    "frase_chave": "Uma frase que expõe a sombra principal do usuário",
    "medo_raiz": "O medo mais profundo identificado",
    "padrao_repetitivo": "O padrão que o usuário repete sem perceber"
}}"""

POTENCIA_PROMPT = """Você é Luna, a inteligência simbólica do Vibra EU. Agora você vai mostrar o PODER da combinação DISC + MAC quando usados conscientemente.

## DADOS DO DISC
- Perfil predominante: {perfil_predominante} ({desc_predominante})
- Perfil secundário: {perfil_secundario} ({desc_secundario})
- Distribuição: D={pct_d}%, I={pct_i}%, S={pct_s}%, C={pct_c}%
- Motivação central (DISC): {motivacao_central}
- Zona de Gênio (DISC): {zona_genio}

## DADOS DO MAC (Mapa Astral Cabalístico)
{mac_resumo}

## CONTEXTO DOS INSIGHTS ANTERIORES
- Interferência principal: {interferencia_ponto}
- Sombra comportamental: {sombra_medo}

## SUA TAREFA: AJUSTE FINO DA POTÊNCIA

Agora revele como o usuário pode ALINHAR seu DISC com seu MAC para operar na máxima potência. Este é o insight construtivo e transformador.

Analise:
1. **A Combinação Única**: O que torna este cruzamento DISC+MAC genuinamente poderoso (não genérico)
2. **A Zona de Gênio Integrada**: Onde comportamento e essência se amplificam mutuamente
3. **O Superpoder Escondido**: A qualidade que emerge APENAS quando DISC e MAC estão alinhados
4. **O Caminho de Calibração**: 2-3 ajustes práticos específicos para este perfil
5. **O Futuro Desbloqueado**: Como operando na potência máxima, a trajetória muda

Escreva de forma inspiradora mas fundamentada. Não seja superficial. O texto deve ter 4-5 parágrafos densos.

Retorne um JSON com esta estrutura exata:
{{
    "report": "<div class='insight-content'>CONTEÚDO HTML com <p>, <strong>, <em> — sem <h1> a <h3>, sem markdown</div>",
    "titulo": "Título curto e impactante (max 8 palavras)",
    "frase_chave": "Uma frase que captura o superpoder do usuário",
    "superpoder": "O superpoder único deste cruzamento",
    "calibracoes": ["Ajuste 1", "Ajuste 2", "Ajuste 3"]
}}"""


# ============================================================================
# Helpers
# ============================================================================

def _format_mac_resumo(mac_data: dict) -> str:
    """Formata os dados do MAC em texto legível para o prompt.
    
    Formato da tabela mapas_astrais:
    - sol_signo, lua_signo, ascendente_signo, mc_signo: colunas diretas (ex: "Cap", "Leo")
    - planetas: JSONB array [{planeta: "Sun", signo: "Cap", grau: 280.5, casa: 7}, ...]
    - casas: JSONB array [{casa: 1, signo: "Gem", grau: 70.3}, ...]
    - aspectos: JSONB array [{planeta1: "Sun", planeta2: "Moon", aspecto: "trine", ...}, ...]
    """
    if not mac_data:
        return "MAC não disponível para este usuário."

    linhas = []

    # Signos principais (colunas diretas)
    sol = mac_data.get("sol_signo")
    lua = mac_data.get("lua_signo")
    asc = mac_data.get("ascendente_signo")
    mc = mac_data.get("mc_signo")

    if sol or lua or asc:
        linhas.append("### Trindade Astrológica")
        if sol:
            linhas.append(f"- **Sol** em {SIGNOS.get(sol, sol)} — Essência, identidade central")
        if lua:
            linhas.append(f"- **Lua** em {SIGNOS.get(lua, lua)} — Mundo emocional, inconsciente")
        if asc:
            linhas.append(f"- **Ascendente** em {SIGNOS.get(asc, asc)} — Máscara social, como se apresenta")
        if mc:
            linhas.append(f"- **Meio do Céu** em {SIGNOS.get(mc, mc)} — Propósito, vocação")

    # Posições planetárias (do array JSONB)
    planetas = mac_data.get("planetas", [])
    if planetas and isinstance(planetas, list):
        linhas.append("\n### Posições Planetárias")
        for p in planetas:
            if not isinstance(p, dict):
                continue
            planet_key = p.get("planeta", "")
            planet_name = PLANETAS.get(planet_key, planet_key)
            sign_key = p.get("signo", "")
            sign_name = SIGNOS.get(sign_key, sign_key)
            house = p.get("casa", "")
            if house:
                linhas.append(f"- {planet_name} em {sign_name} (Casa {house})")
            else:
                linhas.append(f"- {planet_name} em {sign_name}")

    # Aspectos
    aspectos = mac_data.get("aspectos", [])
    if aspectos and isinstance(aspectos, list):
        linhas.append("\n### Aspectos Relevantes")
        for asp in aspectos[:8]:  # Limitar a 8 aspectos mais relevantes
            if not isinstance(asp, dict):
                continue
            p1_key = asp.get("planeta1", asp.get("planet1", ""))
            p2_key = asp.get("planeta2", asp.get("planet2", ""))
            p1 = PLANETAS.get(p1_key, p1_key)
            p2 = PLANETAS.get(p2_key, p2_key)
            tipo = asp.get("aspecto", asp.get("aspect", asp.get("type", "")))
            if p1 and p2 and tipo:
                linhas.append(f"- {p1} ↔ {p2}: {tipo}")

    if not linhas:
        return "Dados do MAC parcialmente disponíveis — sem posições planetárias."

    return "\n".join(linhas)


async def _buscar_dados_complementares(user_id: str) -> Dict[str, Any]:
    """Busca MAC e perfil comportamental do Supabase."""
    supabase = get_supabase_client()
    dados = {"mac": None, "perfil_comportamental": None}

    try:
        # Buscar MAC da tabela mapas_astrais (1 mapa por usuario)
        mac_res = supabase.table("mapas_astrais") \
            .select("sol_signo, lua_signo, ascendente_signo, mc_signo, planetas, casas, aspectos") \
            .eq("user_id", user_id) \
            .maybe_single() \
            .execute()
        if mac_res.data:
            dados["mac"] = mac_res.data
            logger.info(f"[DISC] MAC encontrado: Sol={mac_res.data.get('sol_signo')}, Lua={mac_res.data.get('lua_signo')}, Asc={mac_res.data.get('ascendente_signo')}")
        else:
            logger.warning(f"[DISC] MAC não encontrado para user_id={user_id}")
    except Exception as e:
        logger.warning(f"[DISC] Erro ao buscar MAC: {e}")

    try:
        # Buscar perfil comportamental (se existir)
        perfil_res = supabase.table("behavioral_profile") \
            .select("profile_data") \
            .eq("user_id", user_id) \
            .maybe_single() \
            .execute()
        if perfil_res.data and perfil_res.data.get("profile_data"):
            dados["perfil_comportamental"] = perfil_res.data["profile_data"]
    except Exception as e:
        logger.warning(f"[DISC] Erro ao buscar perfil comportamental: {e}")

    return dados


def _montar_dados_prompt(resultado: dict, dados_complementares: dict) -> dict:
    """Monta o dicionário de variáveis para os prompts."""
    # Perfil predominante e secundário
    predominante = resultado.get("perfil_predominante", "d")
    secundario = resultado.get("perfil_secundario", "i")

    # Calcular percentuais
    d = resultado.get("pontuacao_d", 0)
    i = resultado.get("pontuacao_i", 0)
    s = resultado.get("pontuacao_s", 0)
    c = resultado.get("pontuacao_c", 0)
    total = d + i + s + c or 1
    pct_d = round((d / total) * 100)
    pct_i = round((i / total) * 100)
    pct_s = round((s / total) * 100)
    pct_c = round((c / total) * 100)

    # Perfil mais baixo
    perfis_pct = {"d": pct_d, "i": pct_i, "s": pct_s, "c": pct_c}
    mais_baixo = min(perfis_pct, key=perfis_pct.get)

    # MAC formatado
    mac_data = dados_complementares.get("mac")
    mac_resumo = _format_mac_resumo(mac_data)

    # Zona de gênio (combina predominante + secundário)
    zonas_genio = {
        "di": "Liderança carismática e velocidade de execução com influência social",
        "id": "Liderança carismática e velocidade de execução com influência social",
        "ds": "Liderança estável — combina determinação com consistência e lealdade",
        "sd": "Liderança estável — combina determinação com consistência e lealdade",
        "dc": "Execução estratégica — combina resultados com análise rigorosa",
        "cd": "Execução estratégica — combina resultados com análise rigorosa",
        "is": "Conexão genuína — entusiasmo com empatia e cuidado profundo",
        "si": "Conexão genuína — entusiasmo com empatia e cuidado profundo",
        "ic": "Comunicação precisa — carisma com fundamentação e dados",
        "ci": "Comunicação precisa — carisma com fundamentação e dados",
        "sc": "Consistência analítica — estabilidade com rigor técnico e qualidade",
        "cs": "Consistência analítica — estabilidade com rigor técnico e qualidade",
    }

    combo = predominante + secundario
    zona_genio = zonas_genio.get(combo, f"Combinação {PERFIS_DISC[predominante]['nome']} + {PERFIS_DISC[secundario]['nome']}")

    return {
        "perfil_predominante": PERFIS_DISC[predominante]["nome"],
        "desc_predominante": PERFIS_DISC[predominante]["nome"],
        "perfil_secundario": PERFIS_DISC[secundario]["nome"],
        "desc_secundario": PERFIS_DISC[secundario]["nome"],
        "pct_d": pct_d,
        "pct_i": pct_i,
        "pct_s": pct_s,
        "pct_c": pct_c,
        "medo_central": PERFIS_DISC[predominante]["medo"],
        "motivacao_central": PERFIS_DISC[predominante]["motivacao"],
        "perfil_mais_baixo": PERFIS_DISC[mais_baixo]["nome"],
        "desc_mais_baixo": PERFIS_DISC[mais_baixo]["nome"],
        "mac_resumo": mac_resumo,
        "zona_genio": zona_genio,
        # Serão preenchidos após os insights anteriores
        "interferencia_ponto": "",
        "sombra_medo": "",
    }


def _parse_llm_json(raw_response: str) -> Dict[str, Any]:
    """Extrai JSON da resposta da LLM, lidando com markdown e texto extra."""
    if not raw_response:
        return {"report": "<p>Resposta vazia da IA.</p>"}

    text = raw_response.strip()

    # Remover ```json ... ``` se presente
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove primeira e última linhas
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    # Tentar achar JSON entre chaves
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"[DISC] JSON inválido da LLM, retornando texto bruto")
        return {"report": f"<div class='insight-content'><p>{raw_response[:3000]}</p></div>"}


async def _gerar_insight(
    prompt_template: str,
    dados_prompt: dict,
    insight_name: str
) -> Dict[str, Any]:
    """Gera um insight individual chamando a LLM."""
    try:
        prompt = prompt_template.format(**dados_prompt)
    except KeyError as e:
        logger.warning(f"[DISC] Chave faltando no prompt {insight_name}: {e}")
        prompt = prompt_template
        for k, v in dados_prompt.items():
            prompt = prompt.replace("{" + k + "}", str(v))

    gateway = LLMGateway.get_instance()
    raw_response = await gateway.generate(
        prompt=prompt,
        system_prompt="Você é Luna do Vibra EU. Retorne APENAS JSON válido sem texto antes ou depois.",
        config={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "fallback_provider": "groq",
            "fallback_model": "llama-3.3-70b-versatile",
            "temperature": 0.7,
            "max_tokens": 5000,
        },
    )

    return _parse_llm_json(raw_response)


# ============================================================================
# FUNÇÃO PRINCIPAL — Gera os 3 insights DISC
# ============================================================================

async def gerar_insights_disc(
    user_id: str,
    assessment_id: str,
    resultado: dict,
) -> Dict[str, Any]:
    """
    Gera os 3 insights DISC (Interferência, Sombra, Potência).
    1. Busca dados complementares (MAC, perfil)
    2. Gera cada insight sequencialmente (o 3º recebe contexto dos anteriores)
    3. Salva progressivamente na tabela disc_insights
    """
    supabase = get_supabase_client()

    logger.info(f"[DISC] Iniciando geração de insights para {user_id} (assessment: {assessment_id})")

    # 1. Buscar dados complementares
    dados_complementares = await _buscar_dados_complementares(user_id)

    # 2. Montar dados para prompts
    dados_prompt = _montar_dados_prompt(resultado, dados_complementares)

    # ── INSIGHT 1: INTERFERÊNCIA DESTRUTIVA ──
    logger.info("[DISC] Gerando INTERFERÊNCIA...")
    try:
        interferencia = await _gerar_insight(INTERFERENCIA_PROMPT, dados_prompt, "interferencia")
    except Exception as e:
        logger.error(f"[DISC] Erro ao gerar Interferência: {e}")
        interferencia = {
            "report": f"<div class='insight-content'><p>Erro ao gerar a análise de interferência: {str(e)[:200]}</p></div>",
            "titulo": "Erro na Análise",
            "frase_chave": "",
        }

    # Salvar Interferência imediatamente (para polling)
    try:
        supabase.table("disc_insights").update({
            "insight_interferencia": interferencia,
            "status": "generating",
        }).eq("user_id", user_id).eq("assessment_id", assessment_id).execute()
        logger.info("[DISC] ✅ Interferência salva")
    except Exception as e:
        logger.error(f"[DISC] Erro ao salvar Interferência: {e}")

    # ── INSIGHT 2: SOMBRA COMPORTAMENTAL ──
    logger.info("[DISC] Gerando SOMBRA...")
    try:
        sombra = await _gerar_insight(SOMBRA_PROMPT, dados_prompt, "sombra")
    except Exception as e:
        logger.error(f"[DISC] Erro ao gerar Sombra: {e}")
        sombra = {
            "report": f"<div class='insight-content'><p>Erro ao gerar a análise de sombra: {str(e)[:200]}</p></div>",
            "titulo": "Erro na Análise",
            "frase_chave": "",
        }

    # Salvar Sombra
    try:
        supabase.table("disc_insights").update({
            "insight_sombra": sombra,
        }).eq("user_id", user_id).eq("assessment_id", assessment_id).execute()
        logger.info("[DISC] ✅ Sombra salva")
    except Exception as e:
        logger.error(f"[DISC] Erro ao salvar Sombra: {e}")

    # ── INSIGHT 3: POTÊNCIA (recebe contexto dos anteriores) ──
    logger.info("[DISC] Gerando POTÊNCIA...")
    dados_prompt["interferencia_ponto"] = interferencia.get("ponto_critico", "não identificado")
    dados_prompt["sombra_medo"] = sombra.get("medo_raiz", "não identificado")

    try:
        potencia = await _gerar_insight(POTENCIA_PROMPT, dados_prompt, "potencia")
    except Exception as e:
        logger.error(f"[DISC] Erro ao gerar Potência: {e}")
        potencia = {
            "report": f"<div class='insight-content'><p>Erro ao gerar a análise de potência: {str(e)[:200]}</p></div>",
            "titulo": "Erro na Análise",
            "frase_chave": "",
        }

    # ── SALVAR TUDO COMO COMPLETO ──
    try:
        supabase.table("disc_insights").update({
            "insight_interferencia": interferencia,
            "insight_sombra": sombra,
            "insight_potencia": potencia,
            "status": "available",
        }).eq("user_id", user_id).eq("assessment_id", assessment_id).execute()
        logger.info("[DISC] ✅ Todos os insights salvos com sucesso")
    except Exception as e:
        logger.error(f"[DISC] Erro ao salvar insights finais: {e}")
        # Marcar como erro
        try:
            supabase.table("disc_insights").update({
                "status": "error",
                "error_message": str(e)[:500],
            }).eq("user_id", user_id).eq("assessment_id", assessment_id).execute()
        except Exception:
            pass

    # ── NOTIFICAÇÃO ──
    try:
        supabase.table("notifications").insert({
            "user_id": user_id,
            "type": "star",
            "icon": "fa-chart-pie",
            "icon_color": "#9333ea",
            "title": "📊 Insights DISC Prontos!",
            "message": "A Luna terminou de analisar seu perfil DISC. Interferência, Sombra e Potência estão prontos.",
            "link": "/disc",
            "is_read": False,
        }).execute()
    except Exception as e:
        logger.warning(f"[DISC] Erro ao criar notificação: {e}")

    logger.info(f"[DISC] ✅ Geração completa para {user_id}")

    return {
        "success": True,
        "interferencia": interferencia,
        "sombra": sombra,
        "potencia": potencia,
    }
