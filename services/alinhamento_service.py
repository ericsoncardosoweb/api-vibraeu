"""
Alinhamento Service — Geração dos insights de alinhamento via IA.
Relatórios: O Espelho, O Fluxo, O Caminho.

Lógica:
1. Coleta todos os dados do usuário (check-in, MAC, roda da vida,
   perfil comportamental, relatórios mensais)
2. Decide o cenário baseado na frescura/relevância dos dados
3. Escolhe o prompt otimizado para o cenário
4. Gera cada insight e salva na tabela alinhamento_insights
"""

from datetime import datetime
from typing import Optional, Dict, Any
from loguru import logger
import json
import random

from services.supabase_client import get_supabase_client
from services.llm_gateway import LLMGateway
from services.monthly_reports_service import get_mes_referencia


# ============================================================================
# Mapeamentos — signos e planetas para formato legível
# ============================================================================

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

ELEMENTOS = {"Fire": "Fogo", "Earth": "Terra", "Air": "Ar", "Water": "Água"}

SIGNO_ELEMENTO = {
    "Ari": "Fogo", "Tau": "Terra", "Gem": "Ar", "Can": "Água",
    "Leo": "Fogo", "Vir": "Terra", "Lib": "Ar", "Sco": "Água",
    "Sag": "Fogo", "Cap": "Terra", "Aqu": "Ar", "Pis": "Água"
}

ASPECTOS = {
    "conjunction": "Conjunção", "opposition": "Oposição",
    "trine": "Trígono", "square": "Quadratura",
    "sextile": "Sextil", "quintile": "Quintil"
}


# ============================================================================
# Numerologia — cálculos do Ano Pessoal e Ano Universal
# ============================================================================

ANO_PESSOAL_TEMAS = {
    1: {"titulo": "Novos Começos", "energia": "pioneira", "foco": "iniciar projetos, liderar, ser independente", "evitar": "hesitação, dependência, viver no passado"},
    2: {"titulo": "Parcerias e Paciência", "energia": "receptiva", "foco": "parcerias, diplomacia, paciência", "evitar": "decisões precipitadas, conflitos, impaciência"},
    3: {"titulo": "Expressão e Alegria", "energia": "expressiva", "foco": "criatividade, comunicação, alegria", "evitar": "dispersão, superficialidade"},
    4: {"titulo": "Trabalho e Estrutura", "energia": "construtora", "foco": "organização, disciplina, construção", "evitar": "atalhos, preguiça, rigidez excessiva"},
    5: {"titulo": "Liberdade e Mudanças", "energia": "dinâmica", "foco": "flexibilidade, aventura, novidades", "evitar": "resistir a mudanças, rotina excessiva"},
    6: {"titulo": "Família e Responsabilidade", "energia": "amorosa", "foco": "família, lar, responsabilidade afetiva", "evitar": "sacrifício excessivo, controle"},
    7: {"titulo": "Introspecção e Sabedoria", "energia": "contemplativa", "foco": "autoconhecimento, estudo, espiritualidade", "evitar": "isolamento excessivo, ignorar intuição"},
    8: {"titulo": "Poder e Abundância", "energia": "poderosa", "foco": "finanças, autoridade, realizações", "evitar": "ganância, abuso de poder"},
    9: {"titulo": "Conclusão e Desapego", "energia": "conclusiva", "foco": "finalização, perdão, generosidade", "evitar": "apegar-se ao passado, rancor"},
    11: {"titulo": "Ano Mestre de Intuição", "energia": "iluminada", "foco": "intuição, inspirar outros, propósito de vida", "evitar": "duvidar de si, tensão nervosa"},
    22: {"titulo": "Ano Mestre de Construção", "energia": "visionária", "foco": "grandes projetos, liderança, legado", "evitar": "perfeccionismo paralisante, medo de falhar"},
    33: {"titulo": "Ano Mestre de Cura", "energia": "curadora", "foco": "cura, serviço, amor incondicional", "evitar": "martírio, esquecer de si"},
}


def _reduzir_digito(n: int) -> int:
    """Reduz número a um dígito, preservando mestres (11, 22, 33)."""
    while n > 9 and n not in (11, 22, 33):
        n = sum(int(d) for d in str(n))
    return n


def calcular_ano_universal(ano: int) -> int:
    """Calcula o Ano Universal (soma dos dígitos do ano)."""
    soma = sum(int(d) for d in str(ano))
    while soma > 9 and soma not in (11, 22):
        soma = sum(int(d) for d in str(soma))
    return soma


def calcular_ano_pessoal(data_nascimento: str, ano_atual: int = None) -> Optional[int]:
    """Calcula o Ano Pessoal baseado na data de nascimento."""
    if not data_nascimento:
        return None
    if ano_atual is None:
        ano_atual = datetime.utcnow().year

    try:
        # Suporta YYYY-MM-DD
        parts = data_nascimento[:10].split("-")
        if len(parts) != 3:
            return None
        dia = int(parts[2])
        mes = int(parts[1])
    except (ValueError, IndexError):
        return None

    dm_reduzido = _reduzir_digito(dia + mes)
    ano_uni = calcular_ano_universal(ano_atual)
    return _reduzir_digito(dm_reduzido + ano_uni)


def formatar_numerologia_compacta(data_nascimento: str, numerologia_db: dict = None) -> str:
    """Formata dados de numerologia para o prompt."""
    agora = datetime.utcnow()
    ano_atual = agora.year

    ano_pessoal = calcular_ano_pessoal(data_nascimento, ano_atual)
    ano_universal = calcular_ano_universal(ano_atual)

    partes = []
    partes.append(f"ANO UNIVERSAL {ano_atual}: {ano_universal}")

    if ano_pessoal:
        tema = ANO_PESSOAL_TEMAS.get(ano_pessoal, {})
        partes.append(
            f"ANO PESSOAL: {ano_pessoal} — {tema.get('titulo', '')} "
            f"(energia {tema.get('energia', '')}) | "
            f"Foco: {tema.get('foco', '')} | Evitar: {tema.get('evitar', '')}"
        )

    if numerologia_db:
        nomes = {
            "numeroDestino": "Destino", "numeroExpressao": "Expressão",
            "numeroMotivacao": "Motivação", "numeroCaminho": "Caminho",
            "numeroAlma": "Alma", "numeroPersonalidade": "Personalidade",
        }
        nums = []
        for k, label in nomes.items():
            v = numerologia_db.get(k)
            if v:
                nums.append(f"{label}: {v}")
        if nums:
            partes.append("NÚMEROS: " + " | ".join(nums))

    return "\n".join(partes) if partes else "Numerologia não disponível"


# ============================================================================
# Formatação compacta do MAC (econômica para prompts)
# ============================================================================

def formatar_mac_compacto(mac_data: Dict[str, Any]) -> str:
    """
    Converte MAC completo para formato compacto e legível.
    Inclui: planetas com signos, signos nas 12 casas, aspectos, elementos.
    """
    if not mac_data:
        return "MAC não disponível"

    partes = []

    # 1. Planetas com signos traduzidos
    planetas = mac_data.get("planetas") or []
    planetas_str = []
    for p in planetas:
        planeta_nome = PLANETAS.get(p.get("planeta"), p.get("planeta", ""))
        signo_nome = SIGNOS.get(p.get("signo"), p.get("signo", ""))
        if planeta_nome and signo_nome:
            planetas_str.append(f"{planeta_nome}: {signo_nome}")

    if planetas_str:
        partes.append("PLANETAS: " + " | ".join(planetas_str))

    # 2. Signos nas casas
    casas = mac_data.get("casas") or []
    casas_str = []
    for c in casas:
        casa_num = c.get("casa")
        signo_nome = SIGNOS.get(c.get("signo"), c.get("signo", ""))
        if casa_num and signo_nome:
            casas_str.append(f"Casa {casa_num}: {signo_nome}")

    if casas_str:
        partes.append("CASAS: " + " | ".join(casas_str))

    # 3. Destaques rápidos (para LLM identificar o essencial)
    sol = SIGNOS.get(mac_data.get("sol_signo"), mac_data.get("sol_signo", "?"))
    lua = SIGNOS.get(mac_data.get("lua_signo"), mac_data.get("lua_signo", "?"))
    asc = SIGNOS.get(mac_data.get("ascendente_signo"), mac_data.get("ascendente_signo", "?"))
    mc = SIGNOS.get(mac_data.get("mc_signo"), mac_data.get("mc_signo", "?"))
    partes.insert(0, f"ESSÊNCIA: Sol {sol} | Lua {lua} | Asc {asc} | MC {mc}")

    # 4. Aspectos (resumidos)
    aspectos = mac_data.get("aspectos") or []
    if aspectos:
        aspectos_str = []
        for a in aspectos[:10]:  # Top 10 aspectos
            p1 = PLANETAS.get(a.get("planeta1"), a.get("planeta1", ""))
            p2 = PLANETAS.get(a.get("planeta2"), a.get("planeta2", ""))
            tipo = ASPECTOS.get(a.get("aspecto"), a.get("aspecto", ""))
            if p1 and p2 and tipo:
                aspectos_str.append(f"{p1}-{p2} ({tipo})")
        if aspectos_str:
            partes.append("ASPECTOS: " + " | ".join(aspectos_str))

    # 5. Distribuição elemental
    elementos = _calcular_elementos(planetas, mac_data)
    if elementos:
        partes.append(f"ELEMENTOS: Fogo {elementos['fogo']}% | Terra {elementos['terra']}% | Ar {elementos['ar']}% | Água {elementos['agua']}%")

    return "\n".join(partes)


def _calcular_elementos(planetas: list, mac_data: dict) -> Optional[dict]:
    """Calcula distribuição de elementos do MAC."""
    PESOS = {
        "Sun": 2, "Moon": 2,
        "Mercury": 4, "Venus": 4, "Mars": 4,
        "Jupiter": 4, "Saturn": 4,
        "Uranus": 1, "Neptune": 1, "Pluto": 1
    }

    soma = {"Fogo": 0, "Terra": 0, "Ar": 0, "Água": 0}

    for p in planetas:
        peso = PESOS.get(p.get("planeta"), 0)
        elemento = SIGNO_ELEMENTO.get(p.get("signo"))
        if peso and elemento:
            soma[elemento] += peso

    # ASC e MC
    asc_el = SIGNO_ELEMENTO.get(mac_data.get("ascendente_signo"))
    if asc_el:
        soma[asc_el] += 0.5
    mc_el = SIGNO_ELEMENTO.get(mac_data.get("mc_signo"))
    if mc_el:
        soma[mc_el] += 0.5

    total = sum(soma.values())
    if total == 0:
        return None

    return {
        "fogo": round(soma["Fogo"] / total * 100),
        "terra": round(soma["Terra"] / total * 100),
        "ar": round(soma["Ar"] / total * 100),
        "agua": round(soma["Água"] / total * 100),
    }


# ============================================================================
# Coleta de dados complementares
# ============================================================================

async def buscar_dados_complementares(user_id: str, mes_referencia: str) -> Dict[str, Any]:
    """
    Busca todos os dados complementares do usuário para decidir cenário e montar prompt.
    Retorna: mac, roda_da_vida, perfil_comportamental, relatorio_diario, relatorio_metas, numerologia.
    """
    supabase = get_supabase_client()

    # MAC
    mac_data = None
    try:
        resp = supabase.table("mapas_astrais") \
            .select("*") \
            .eq("user_id", user_id) \
            .maybe_single() \
            .execute()
        mac_data = resp.data
    except Exception as e:
        logger.warning(f"[Alinhamento] Erro ao buscar MAC: {e}")

    # Roda da Vida (mais recente)
    roda_da_vida = None
    try:
        resp = supabase.table("life_wheel_assessments") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        roda_da_vida = resp.data[0] if resp.data else None
    except Exception as e:
        logger.warning(f"[Alinhamento] Erro ao buscar Roda da Vida: {e}")

    # Perfil Comportamental (mais recente)
    perfil_comportamental = None
    try:
        resp = supabase.table("behavioral_profile_assessments") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        perfil_comportamental = resp.data[0] if resp.data else None
    except Exception as e:
        logger.warning(f"[Alinhamento] Erro ao buscar Perfil Comportamental: {e}")


    # Relatório Mensal do Diário
    relatorio_diario = None
    try:
        resp = supabase.table("monthly_reports") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("report_type", "diario") \
            .eq("mes_referencia", mes_referencia) \
            .eq("status", "available") \
            .maybe_single() \
            .execute()
        relatorio_diario = resp.data
    except Exception as e:
        logger.warning(f"[Alinhamento] Erro ao buscar relatório diário: {e}")

    # Relatório Mensal de Metas
    relatorio_metas = None
    try:
        resp = supabase.table("monthly_reports") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("report_type", "metas") \
            .eq("mes_referencia", mes_referencia) \
            .eq("status", "available") \
            .maybe_single() \
            .execute()
        relatorio_metas = resp.data
    except Exception as e:
        logger.warning(f"[Alinhamento] Erro ao buscar relatório metas: {e}")

    return {
        "mac": mac_data,
        "roda_da_vida": roda_da_vida,
        "perfil_comportamental": perfil_comportamental,
        "relatorio_diario": relatorio_diario,
        "relatorio_metas": relatorio_metas,
    }


# ============================================================================
# Decisão de cenário
# ============================================================================

def decidir_cenario(dados: Dict[str, Any]) -> str:
    """
    Decide qual cenário de prompt usar baseado na frescura e relevância dos dados.
    Retorna: RODA_CENTRO, PERFIL_DESTAQUE, DADOS_CONCRETOS ou ESSENCIA_MAC.
    """
    agora = datetime.utcnow()

    # Roda da Vida preenchida nos últimos 30 dias?
    roda = dados.get("roda_da_vida")
    roda_recente = False
    if roda and roda.get("created_at"):
        try:
            roda_date = datetime.fromisoformat(roda["created_at"].replace("Z", "+00:00")).replace(tzinfo=None)
            roda_recente = (agora - roda_date).days < 30
        except (ValueError, TypeError):
            pass

    # Perfil Comportamental preenchido nos últimos 30 dias?
    perfil = dados.get("perfil_comportamental")
    perfil_recente = False
    if perfil and perfil.get("created_at"):
        try:
            perfil_date = datetime.fromisoformat(perfil["created_at"].replace("Z", "+00:00")).replace(tzinfo=None)
            perfil_recente = (agora - perfil_date).days < 30
        except (ValueError, TypeError):
            pass

    # Relatórios mensais fortes (score >= 6)?
    diario = dados.get("relatorio_diario")
    diario_score = 0
    if diario and diario.get("report_data"):
        diario_score = diario["report_data"].get("relevance_score", 0)
        if isinstance(diario_score, str):
            try:
                diario_score = int(diario_score)
            except ValueError:
                diario_score = 0

    metas = dados.get("relatorio_metas")
    metas_score = 0
    if metas and metas.get("report_data"):
        metas_score = metas["report_data"].get("relevance_score", 0)
        if isinstance(metas_score, str):
            try:
                metas_score = int(metas_score)
            except ValueError:
                metas_score = 0

    diario_forte = diario_score >= 6
    metas_forte = metas_score >= 6

    cenario = "ESSENCIA_MAC"  # fallback
    if roda_recente:
        cenario = "RODA_CENTRO"
    elif perfil_recente:
        cenario = "PERFIL_DESTAQUE"
    elif diario_forte or metas_forte:
        cenario = "DADOS_CONCRETOS"

    logger.info(
        f"[Alinhamento] Cenário decidido: {cenario} | "
        f"roda_recente={roda_recente} perfil_recente={perfil_recente} "
        f"diario_score={diario_score} metas_score={metas_score}"
    )

    return cenario


# ============================================================================
# Resumo compacto dos relatórios mensais (para enviar no prompt)
# ============================================================================

def _resumo_relatorio(report: Optional[dict], tipo: str) -> str:
    """Gera resumo compacto de um relatório mensal para uso nos prompts."""
    if not report or not report.get("report_data"):
        return f"Relatório de {tipo} não disponível este mês."

    rd = report["report_data"]
    score = rd.get("relevance_score", "?")

    if tipo == "diário":
        parts = [f"Score: {score}/10"]
        if rd.get("total_entries"):
            parts.append(f"{rd['total_entries']} registros no mês")
        if rd.get("avg_mood"):
            parts.append(f"humor médio: {rd['avg_mood']}/5")
        if rd.get("emotion_balance"):
            eb = rd["emotion_balance"]
            parts.append(f"emocional: {eb.get('positive', 0)}% positivo / {eb.get('negative', 0)}% negativo")
        if rd.get("top_emotions"):
            top3 = [e["label"] for e in rd["top_emotions"][:3]]
            parts.append(f"top emoções: {', '.join(top3)}")
        if rd.get("patterns_identified"):
            parts.append(f"padrões: {', '.join(rd['patterns_identified'][:3])}")
        return " | ".join(parts)

    elif tipo == "metas":
        parts = [f"Score: {score}/10"]
        if rd.get("total_habitos_ativos") is not None:
            parts.append(f"{rd['total_habitos_ativos']} hábitos ativos")
        if rd.get("total_projetos_ativos") is not None:
            parts.append(f"{rd['total_projetos_ativos']} projetos ativos")
        if rd.get("avg_streak"):
            parts.append(f"streak médio: {rd['avg_streak']}d")
        if rd.get("avg_progress_projetos"):
            parts.append(f"progresso médio: {rd['avg_progress_projetos']}%")
        if rd.get("taxa_realizacao"):
            parts.append(f"taxa de compromisso: {rd['taxa_realizacao']}%")
        if rd.get("areas_negligenciadas"):
            areas = [a.get("area", "") for a in rd["areas_negligenciadas"][:3]]
            parts.append(f"áreas negligenciadas: {', '.join(areas)}")
        return " | ".join(parts)

    return ""


# ============================================================================
# 4 Prompts do ESPELHO
# ============================================================================

ESPELHO_RODA_CENTRO = """Você é Luna, a mentora de autoconhecimento do app Vibra EU.

MISSÃO: Confrontar com amor a autopercepção do usuário (Roda da Vida + Check-in) com a realidade que seus registros emocionais e ações revelam. O Espelho mostra o que ele talvez não esteja enxergando.

DADOS:
- Data: {data_atual} | Mês: {mes_referencia}
- Perfil: {perfil}
- MAC:
{mac_compacto}
- Check-in do Alinhamento: {checkin}
- Roda da Vida ({roda_dias} dias atrás): {roda_da_vida}
- Relatório Mensal do Diário: {resumo_diario}
- Relatório Mensal de Metas: {resumo_metas}

ANÁLISE OBRIGATÓRIA:
1. A Roda da Vida é recente — ela é o CENTRO. Compare cada área da Roda com:
   - O que o check-in do alinhamento revela sobre essas mesmas áreas
   - O que o diário de bordo registrou (emoções reais, humor, fatores)
   - O que as metas/hábitos mostram de ação concreta
2. PONTOS CEGOS: Onde ele se deu nota alta na Roda mas os dados mostram outra coisa?
3. FORÇAS NÃO VISTAS: Onde os dados mostram progresso que ele não reconhece?
4. NEGLIGÊNCIA: Onde tudo está baixo — ele sabe mas não age?
5. Cite dados concretos: emoções específicas, números, metas específicas.
6. Considere as energias do MAC para contextualizar as tendências.

TOM: Amoroso, profundo, direto. Metáforas de reflexo e visão. Emojis estratégicos (🪞✨💫). Mínimo 800 palavras. Desfecho épico.

HTML: <h3> subtítulos, <p> parágrafos, <strong> ênfase, <ul>/<li> listas, <blockquote> citações impactantes.

RETORNE APENAS JSON:
{{"report": "HTML extenso", "main_blind_spot": "Área com maior dissonância", "main_strength": "Força não reconhecida", "dissonance_level": "Baixo|Médio|Alto", "final_phrase": "Frase épica"}}"""


ESPELHO_PERFIL_DESTAQUE = """Você é Luna, a mentora de autoconhecimento do app Vibra EU.

MISSÃO: Revelar como o estilo comportamental do usuário influencia sua percepção de si mesmo. O Espelho mostra se ele está agindo conforme sua natureza ou contra ela.

DADOS:
- Data: {data_atual} | Mês: {mes_referencia}
- Perfil: {perfil}
- MAC:
{mac_compacto}
- Check-in do Alinhamento: {checkin}
- Perfil Comportamental ({perfil_dias} dias atrás): {perfil_comportamental}
  (Gato=harmonia/afeto | Lobo=lealdade/estrutura | Tubarão=ação/resultado | Águia=visão/inovação)
- Relatório Mensal do Diário: {resumo_diario}
- Relatório Mensal de Metas: {resumo_metas}

ANÁLISE OBRIGATÓRIA:
1. O perfil comportamental revela COMO ele processa a vida. Compare com:
   - O que o check-in mostra (como ele SE VÊ)
   - O que o diário revela (como REALMENTE se sentiu)
   - O que as metas mostram (como REALMENTE agiu)
2. Ele está agindo conforme seu perfil dominante ou contra sua natureza?
3. O estilo dele explica algum padrão emocional do mês?
4. Onde o perfil comportamental é uma FORÇA e onde vira auto-sabotagem?
5. Use o MAC para contextualizar as tendências astrológicas que reforçam ou desafiam o perfil.
6. Cite dados concretos dos relatórios mensais.

TOM: Amoroso, profundo, direto. Metáforas de reflexo e identidade. Emojis estratégicos (🪞✨💫). Mínimo 800 palavras. Desfecho épico.

HTML: <h3> subtítulos, <p> parágrafos, <strong> ênfase, <ul>/<li> listas.

RETORNE APENAS JSON:
{{"report": "HTML extenso", "main_blind_spot": "Área com maior dissonância", "main_strength": "Força não reconhecida", "dissonance_level": "Baixo|Médio|Alto", "final_phrase": "Frase épica"}}"""


ESPELHO_DADOS_CONCRETOS = """Você é Luna, a mentora de autoconhecimento do app Vibra EU.

MISSÃO: Confrontar o que o usuário DIZ sobre si (check-in) com o que seus registros do mês PROVAM. O Espelho usa dados concretos para revelar a verdade.

DADOS:
- Data: {data_atual} | Mês: {mes_referencia}
- Perfil: {perfil}
- MAC:
{mac_compacto}
- Check-in do Alinhamento: {checkin}
- Relatório Mensal do Diário: {resumo_diario}
- Relatório Mensal de Metas: {resumo_metas}

ANÁLISE OBRIGATÓRIA:
1. O TRIÂNGULO DA VERDADE:
   - O que DISSE no check-in (autopercepção)
   - O que SENTIU de verdade (diário — emoções, humor, fatores)
   - O que FEZ de fato (metas, hábitos, streaks, progresso)
2. Onde há harmonia entre os 3? Celebre.
3. Onde há dissonância? Revele com gentileza e dados concretos.
4. O MAC contextualiza tendências — use para dar profundidade.
5. Cite números, emoções e metas ESPECÍFICAS dos dados.

TOM: Amoroso, profundo, direto. Metáforas de reflexo e verdade. Emojis estratégicos (🪞✨💫). Mínimo 800 palavras. Desfecho épico.

HTML: <h3> subtítulos, <p> parágrafos, <strong> ênfase, <ul>/<li> listas.

RETORNE APENAS JSON:
{{"report": "HTML extenso", "main_blind_spot": "Área com maior dissonância", "main_strength": "Força não reconhecida", "dissonance_level": "Baixo|Médio|Alto", "final_phrase": "Frase épica"}}"""


ESPELHO_ESSENCIA_MAC = """Você é Luna, a mentora de autoconhecimento do app Vibra EU.

MISSÃO: Quando os dados concretos são escassos, o Espelho usa a essência astrológica do usuário como bússola. A vida pode estar passando e ele pode não estar assumindo o controle.

DADOS:
- Data: {data_atual} | Mês: {mes_referencia}
- Perfil: {perfil}
- MAC:
{mac_compacto}
- Check-in do Alinhamento: {checkin}
- Dados do Diário: {resumo_diario}
- Dados de Metas: {resumo_metas}

ANÁLISE OBRIGATÓRIA:
1. O MAC revela quem ele É na essência. O check-in mostra como ele SE VÊ agora.
2. Ele está vivendo de acordo com sua essência astrológica ou contra ela?
3. O que as energias do Sol, Lua e Ascendente pedem dele neste momento?
4. Os aspectos e a distribuição elemental indicam desafios ou facilitadores?
5. Se há poucos registros no diário/metas, isso POR SI SÓ é um dado — pode indicar desconexão consigo mesmo. Aborde isso.
6. Provoque reflexão: "O espelho só reflete quando alguém olha para ele."

TOM: Amoroso mas provocativo. Metáforas de despertar e reflexo. Emojis estratégicos (🪞✨💫). Mínimo 800 palavras. Desfecho épico e motivador.

HTML: <h3> subtítulos, <p> parágrafos, <strong> ênfase, <ul>/<li> listas.

RETORNE APENAS JSON:
{{"report": "HTML extenso", "main_blind_spot": "Área com maior dissonância", "main_strength": "Força não reconhecida", "dissonance_level": "Baixo|Médio|Alto", "final_phrase": "Frase épica"}}"""


# ============================================================================
# Variações de perspectiva (evitam relatórios repetitivos)
# ============================================================================

FLUXO_ANGULOS = [
    "Comece pela relação entre o Ano Pessoal e as áreas com menor alinhamento. O desalinhamento é natural ou resistência?",
    "Comece pela energia elemental do MAC e como ela se manifesta no ritmo do mês. O usuário está honrando seu elemento dominante?",
    "Comece pela tensão entre o que o Ano Pessoal pede e o que o MAC naturalmente quer. Há sincronicidade ou atrito?",
    "Comece pelas áreas onde há fluidez e pergunte: o que permite esse fluxo? A resposta está no MAC ou no ciclo numerológico?",
]

CAMINHO_ANGULOS = [
    "Comece pela área que funciona como ALAVANCA — ajustar ela provoca efeito cascata nas demais. Justifique pelo MAC.",
    "Comece pelo FATOR OCULTO — o talento do MAC que o usuário ainda não percebeu ou não está usando.",
    "Comece pela PAUSA ESTRATÉGICA — o que ele está forçando e deveria soltar para o ciclo fluir.",
    "Comece pela OPORTUNIDADE ESCONDIDA — o que os insights do Espelho e Fluxo revelam que ele não conectou ainda.",
]


# ============================================================================
# Prompt do FLUXO (Essência MAC + Tempo Numerológico)
# ============================================================================

FLUXO_PROMPT = """Você é Luna, a mentora de autoconhecimento do app Vibra EU.

MISSÃO: Explicar a dinâmica entre quem o usuário É na essência (seu MAC) e o RITMO que a vida está exigindo dele agora (Numerologia). O Fluxo traz a sensação de que "tudo tem seu tempo".

DADOS:
- Data: {data_atual} | Mês: {mes_referencia}
- Perfil: {perfil}
- MAC:
{mac_compacto}
- Numerologia:
{numerologia_compacta}
- Check-in do Alinhamento: {checkin}
- Relatório Mensal do Diário: {resumo_diario}
- Relatório Mensal de Metas: {resumo_metas}
{dados_extras}

DIRETRIZ DE PERSPECTIVA:
{angulo_fluxo}

ANÁLISE OBRIGATÓRIA:
1. **Sincronicidade de Tempo:** Os desafios atuais (áreas com baixo alinhamento no check-in) são reflexos naturais do Ano Pessoal? Ex: Ano 4 exige paciência e estrutura → se "Expansão" está baixo, é esperado e benéfico.
2. **Atrito de Essência:** O usuário está tentando agir contra a natureza do MAC para se encaixar em métricas externas de sucesso/produtividade?
3. **O Fluxo do Ano:** Combine a energia do Ano Universal com o Ano Pessoal para dar uma perspectiva de "Clima Espiritual" do momento.
4. **Validação pelo Diário/Metas:** Os dados concretos (emoções, hábitos, progresso) confirmam ou contradizem o fluxo esperado pelo ciclo?
5. Onde há FLUIDEZ genuína (métricas altas + ciclo favorável)? Celebre.
6. Onde há RESISTÊNCIA (métricas baixas + ciclo que pede soltar)? Oriente com compaixão.

TOM: Sábio, rítmico, calmo e profundo. Foque no significado emocional e prático das energias. Evite termos técnicos pesados. Metáforas de tempo, marés e estações. Emojis estratégicos (🌊✨🕰️). Mínimo 800 palavras. Desfecho com aceitação do tempo.

HTML: <h3> subtítulos, <p> parágrafos, <strong> ênfase, <ul>/<li> listas.

RETORNE APENAS JSON:
{{"report": "HTML extenso", "personal_year_theme": "Palavra ou frase do tema do ano", "rhythm_status": "Ex: Em Harmonia com o Ciclo / Resistindo ao Fluxo / Preparando Terreno", "final_phrase": "Frase sobre aceitar o tempo"}}"""


# ============================================================================
# Prompt do CAMINHO (Ações e Estratégia — recebe Espelho + Fluxo como contexto)
# ============================================================================

CAMINHO_PROMPT = """Você é Luna, a mentora de autoconhecimento do app Vibra EU.

MISSÃO: Transformar toda a análise anterior em um plano de ação estratégico, construtivo e SUSTENTÁVEL. O Caminho ajuda o usuário a decidir onde colocar energia e onde "apertar o pause".

DADOS DO USUÁRIO:
- Data: {data_atual} | Mês: {mes_referencia}
- Perfil: {perfil}
- MAC:
{mac_compacto}
- Check-in do Alinhamento: {checkin}
{dados_extras}

INSIGHTS ANTERIORES (CONTEXTO — use como base, NÃO repita):
- O Espelho identificou: ponto cego = "{espelho_blind_spot}", força = "{espelho_strength}", dissonância = "{espelho_dissonance}"
- O Fluxo identificou: tema do ano = "{fluxo_year_theme}", status do ritmo = "{fluxo_rhythm}"

DIRETRIZ DE PERSPECTIVA:
{angulo_caminho}

ANÁLISE OBRIGATÓRIA:
1. **Ação Prioritária (A Alavanca):** Identifique UMA única área que, se ajustada, terá efeito cascata positivo nas outras. Baseie no MAC (ex: se MAC focado em comunicação, a solução pode ser expressar algo travado).
2. **Pausa Estratégica:** O que o usuário está tentando forçar e que deveria ser colocado em "pausa" para evitar esgotamento ou desalinhamento severo?
3. **O Fator Oculto:** Revele algo que o usuário ainda não está vendo ou valorizando — um talento do MAC não usado ou oportunidade ignorada.
4. **3 Micro-ações para as próximas 72h:** Concretas, realizáveis, alinhadas com a essência.
5. Conecte TUDO ao MAC — cada recomendação deve ter fundamento na essência astrológica.
6. Considere Casa 10 (MC — propósito público), Casa 6 (rotina/saúde), Casa 2 (valores/recursos).

TOM: Estratégico, encorajador, focado em lifestyle e "branding pessoal". Leve mas com sensação de segurança. Emojis estratégicos (🧭✨🎯). Mínimo 800 palavras. Desfecho com confiança no próximo passo.

HTML: <h3> subtítulos, <p> parágrafos, <strong> ênfase, <ul>/<li> listas.

RETORNE APENAS JSON:
{{"report": "HTML extenso", "strategic_focus": "Área prioridade nº1", "action_steps": ["micro-ação 1", "micro-ação 2", "micro-ação 3"], "final_phrase": "Frase épica e direcionadora"}}"""


# ============================================================================
# Geração dos insights
# ============================================================================

def _montar_dados_prompt(
    checkin: dict,
    perfil: dict,
    dados: Dict[str, Any],
    cenario: str,
    mes_referencia: str
) -> dict:
    """Monta os dados formatados para inserir nos prompts."""
    agora = datetime.utcnow()

    # MAC compacto
    mac_compacto = formatar_mac_compacto(dados.get("mac"))

    # Perfil formatado
    perfil_str = f"{perfil.get('nome', 'Usuário')}"
    if perfil.get("data_nascimento"):
        try:
            dn = datetime.strptime(perfil["data_nascimento"][:10], "%Y-%m-%d")
            idade = (agora - dn).days // 365
            perfil_str += f", {idade} anos"
        except (ValueError, TypeError):
            pass
    if perfil.get("profissao"):
        perfil_str += f", {perfil['profissao']}"
    if perfil.get("estado_civil"):
        perfil_str += f", {perfil['estado_civil']}"
    if perfil.get("sexo"):
        perfil_str += f", {perfil['sexo']}"

    # Resumos dos relatórios
    resumo_diario = _resumo_relatorio(dados.get("relatorio_diario"), "diário")
    resumo_metas = _resumo_relatorio(dados.get("relatorio_metas"), "metas")

    # Numerologia (calculada localmente, sem DB)
    data_nasc = perfil.get("data_nascimento") or perfil.get("dataNascimento")
    numerologia_compacta = formatar_numerologia_compacta(data_nasc, None)

    base = {
        "data_atual": agora.strftime("%d/%m/%Y"),
        "mes_referencia": mes_referencia,
        "perfil": perfil_str,
        "mac_compacto": mac_compacto,
        "checkin": json.dumps(checkin, ensure_ascii=False),
        "resumo_diario": resumo_diario,
        "resumo_metas": resumo_metas,
        "numerologia_compacta": numerologia_compacta,
        # Ângulos de variação (randomizados)
        "angulo_fluxo": random.choice(FLUXO_ANGULOS),
        "angulo_caminho": random.choice(CAMINHO_ANGULOS),
    }

    # Dados extras por cenário (Espelho)
    if cenario == "RODA_CENTRO":
        roda = dados.get("roda_da_vida")
        roda_dias = 0
        if roda and roda.get("created_at"):
            try:
                roda_date = datetime.fromisoformat(roda["created_at"].replace("Z", "+00:00")).replace(tzinfo=None)
                roda_dias = (agora - roda_date).days
            except (ValueError, TypeError):
                pass
        base["roda_dias"] = roda_dias
        roda_scores = roda.get("scores") or roda.get("areas") or {} if roda else {}
        base["roda_da_vida"] = json.dumps(roda_scores, ensure_ascii=False)

    elif cenario == "PERFIL_DESTAQUE":
        perfil_comp = dados.get("perfil_comportamental")
        perfil_dias = 0
        if perfil_comp and perfil_comp.get("created_at"):
            try:
                p_date = datetime.fromisoformat(perfil_comp["created_at"].replace("Z", "+00:00")).replace(tzinfo=None)
                perfil_dias = (agora - p_date).days
            except (ValueError, TypeError):
                pass
        base["perfil_dias"] = perfil_dias
        base["perfil_comportamental"] = json.dumps(
            perfil_comp.get("results") or perfil_comp.get("resultado") or {},
            ensure_ascii=False
        )

    # Dados extras consolidados (Fluxo e Caminho)
    extras = []
    roda = dados.get("roda_da_vida")
    if roda:
        roda_scores = roda.get("scores") or roda.get("areas") or {}
        extras.append(f"- Roda da Vida: {json.dumps(roda_scores, ensure_ascii=False)}")
    perfil_comp = dados.get("perfil_comportamental")
    if perfil_comp:
        extras.append(f"- Perfil Comportamental: {json.dumps(perfil_comp.get('results') or perfil_comp.get('resultado') or {}, ensure_ascii=False)}")
    base["dados_extras"] = "\n".join(extras)

    # Placeholders para Caminho (preenchidos depois da geração do Espelho e Fluxo)
    base["espelho_blind_spot"] = ""
    base["espelho_strength"] = ""
    base["espelho_dissonance"] = ""
    base["fluxo_year_theme"] = ""
    base["fluxo_rhythm"] = ""

    return base


def _escolher_prompt_espelho(cenario: str) -> str:
    """Retorna o prompt correto do Espelho para o cenário."""
    return {
        "RODA_CENTRO": ESPELHO_RODA_CENTRO,
        "PERFIL_DESTAQUE": ESPELHO_PERFIL_DESTAQUE,
        "DADOS_CONCRETOS": ESPELHO_DADOS_CONCRETOS,
        "ESSENCIA_MAC": ESPELHO_ESSENCIA_MAC,
    }.get(cenario, ESPELHO_ESSENCIA_MAC)


def _parse_llm_json(raw: str) -> Dict[str, Any]:
    """Parseia resposta JSON do LLM com tratamento robusto."""
    import re
    text = raw.strip()

    # 1. Remover code fences (```json ... ```)
    if "```json" in text:
        text = text.split("```json", 1)[1]
        if "```" in text:
            text = text.split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1]
        if "```" in text:
            text = text.split("```", 1)[0]

    text = text.strip()

    # 2. Tentar parse direto
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3. Tentar corrigir newlines não-escaped dentro de strings JSON
    try:
        # Encontrar o JSON object (primeiro { até último })
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = text[start:end]
            # Substituir newlines reais por \n dentro de strings
            # Abordagem: substituir todas as newlines por \\n e tabs por \\t
            fixed = json_str.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n").replace("\t", "\\t")
            return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 4. Fallback: extrair campos via regex
    logger.warning("[Alinhamento] JSON parse falhou, extraindo campos via regex")
    result = {}

    # Extrair report (campo principal com HTML)
    report_match = re.search(r'"report"\s*:\s*"(.*?)(?:"\s*[,}])', text, re.DOTALL)
    if report_match:
        result["report"] = report_match.group(1).replace("\\n", "\n").replace('\\"', '"')
    else:
        # Se não achei o campo report, usar o texto inteiro como HTML
        # Mas limpar qualquer JSON wrapping
        clean = text
        if clean.startswith('{"report":'):
            clean = clean[len('{"report":'):].strip().strip('"')
        if clean.endswith('"}'):
            clean = clean[:-2]
        result["report"] = clean

    # Extrair campos extras
    for field in ["final_phrase", "main_blind_spot", "main_strength", "dissonance_level",
                   "personal_year_theme", "rhythm_status", "strategic_focus"]:
        match = re.search(rf'"{field}"\s*:\s*"([^"]*)"', text)
        if match:
            result[field] = match.group(1)

    # Extrair action_steps (array de strings)
    steps_match = re.search(r'"action_steps"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if steps_match:
        steps_raw = steps_match.group(1)
        result["action_steps"] = [s.strip().strip('"') for s in re.findall(r'"([^"]+)"', steps_raw)]

    if not result.get("final_phrase"):
        result["final_phrase"] = ""

    return result


async def _gerar_insight(
    prompt_template: str,
    dados_prompt: dict,
    insight_name: str
) -> Dict[str, Any]:
    """Gera um insight individual chamando a LLM."""
    try:
        prompt = prompt_template.format(**dados_prompt)
    except KeyError as e:
        logger.warning(f"[Alinhamento] Chave faltando no prompt {insight_name}: {e}")
        # Tentar com format_map que ignora chaves faltantes
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
            "max_tokens": 4000,
        },
    )

    return _parse_llm_json(raw_response)


# ============================================================================
# Função principal — Gerar todos os insights
# ============================================================================

async def gerar_insights_alinhamento(
    user_id: str,
    checkin_id: str,
    checkin_data: dict,
    perfil: dict,
    mes_referencia: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Gera os 3 insights (Espelho, Fluxo, Caminho) para o alinhamento mensal.
    1. Coleta dados complementares do banco
    2. Decide cenário baseado na frescura dos dados
    3. Gera cada insight sequencialmente
    4. Salva resultados na tabela alinhamento_insights
    """
    mes = get_mes_referencia(mes_referencia)
    supabase = get_supabase_client()

    logger.info(f"[Alinhamento] Iniciando geração de insights para {user_id} - {mes}")

    # 1. Coletar dados
    dados = await buscar_dados_complementares(user_id, mes)

    # 2. Decidir cenário
    cenario = decidir_cenario(dados)

    # 3. Montar dados para os prompts
    dados_prompt = _montar_dados_prompt(checkin_data, perfil, dados, cenario, mes)

    # 4. ESPELHO
    logger.info(f"[Alinhamento] Gerando ESPELHO (cenário: {cenario})...")
    try:
        espelho = await _gerar_insight(
            _escolher_prompt_espelho(cenario),
            dados_prompt,
            "espelho"
        )
    except Exception as e:
        logger.error(f"[Alinhamento] Erro ao gerar Espelho: {e}")
        espelho = {"report": f"<p>Erro ao gerar o Espelho: {str(e)[:200]}</p>", "final_phrase": ""}

    # Salvar Espelho imediatamente
    try:
        supabase.table("alinhamento_insights").update({
            "espelho": espelho,
            "status": "generating",
        }).eq("user_id", user_id).eq("mes_referencia", mes).execute()
        logger.info("[Alinhamento] ✅ Espelho salvo")
    except Exception as e:
        logger.error(f"[Alinhamento] Erro ao salvar Espelho: {e}")

    # 5. FLUXO (com numerologia)
    logger.info("[Alinhamento] Gerando FLUXO...")
    try:
        fluxo = await _gerar_insight(FLUXO_PROMPT, dados_prompt, "fluxo")
    except Exception as e:
        logger.error(f"[Alinhamento] Erro ao gerar Fluxo: {e}")
        fluxo = {"report": f"<p>Erro ao gerar o Fluxo: {str(e)[:200]}</p>", "final_phrase": ""}

    # Salvar Fluxo
    try:
        supabase.table("alinhamento_insights").update({
            "fluxo": fluxo,
        }).eq("user_id", user_id).eq("mes_referencia", mes).execute()
        logger.info("[Alinhamento] ✅ Fluxo salvo")
    except Exception as e:
        logger.error(f"[Alinhamento] Erro ao salvar Fluxo: {e}")

    # 6. CAMINHO (recebe contexto do Espelho + Fluxo)
    logger.info("[Alinhamento] Gerando CAMINHO...")
    dados_prompt["espelho_blind_spot"] = espelho.get("main_blind_spot", "não identificado")
    dados_prompt["espelho_strength"] = espelho.get("main_strength", "não identificado")
    dados_prompt["espelho_dissonance"] = espelho.get("dissonance_level", "Médio")
    dados_prompt["fluxo_year_theme"] = fluxo.get("personal_year_theme", "não identificado")
    dados_prompt["fluxo_rhythm"] = fluxo.get("rhythm_status", "não identificado")
    try:
        caminho = await _gerar_insight(CAMINHO_PROMPT, dados_prompt, "caminho")
    except Exception as e:
        logger.error(f"[Alinhamento] Erro ao gerar Caminho: {e}")
        caminho = {"report": f"<p>Erro ao gerar o Caminho: {str(e)[:200]}</p>", "final_phrase": ""}

    # 7. Salvar tudo como completo
    try:
        supabase.table("alinhamento_insights").update({
            "espelho": espelho,
            "fluxo": fluxo,
            "caminho": caminho,
            "status": "available",
        }).eq("user_id", user_id).eq("mes_referencia", mes).execute()
        logger.info("[Alinhamento] ✅ Todos os insights salvos com sucesso")
    except Exception as e:
        logger.error(f"[Alinhamento] Erro ao salvar insights finais: {e}")

    # 8. Criar notificação
    try:
        supabase.table("notifications").insert({
            "user_id": user_id,
            "type": "star",
            "icon": "fa-compass",
            "icon_color": "#9933CC",
            "title": "🧭 Insights de Alinhamento Prontos!",
            "message": "A Luna terminou de analisar seu check-in. O Espelho, o Fluxo e o Caminho estão prontos.",
            "link": "/alinhamento",
            "is_read": False,
        }).execute()
    except Exception as e:
        logger.warning(f"[Alinhamento] Erro ao criar notificação: {e}")

    logger.info(f"[Alinhamento] ✅ Geração completa para {user_id} (cenário: {cenario})")

    return {
        "success": True,
        "cenario": cenario,
        "espelho": espelho,
        "fluxo": fluxo,
        "caminho": caminho,
    }
