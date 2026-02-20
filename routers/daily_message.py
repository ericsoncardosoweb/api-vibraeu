"""
Router: Daily Message (Mensagem do Dia)

Motor de Engenharia Emocional v6.0 — Narrativa de crescimento personalizada.
4 camadas: espelho (identidade) + tensão (conflito) + direção (ação) + frase (reforço).
Tom de mentor lúcido. Ritmo psicológico semanal. Lua estratégica.

Endpoints:
- POST /daily-message/generate — Gera ou retorna mensagem do dia
- POST /daily-message/regenerate — Regenera a mensagem (1x/dia)
- POST /daily-message/rate — Registra rating da mensagem
"""

import json
import random
import re
import pytz
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from loguru import logger

from config import get_settings
from services.supabase_client import SupabaseService
from services.llm_gateway import LLMGateway
from services.astro_engine import gerar_sujeito_final, calcular_fase_lunar

router = APIRouter(prefix="/daily-message")

# ============================================================================
# MODELS
# ============================================================================

class GenerateRequest(BaseModel):
    user_id: Optional[str] = None

class RateRequest(BaseModel):
    mensagem_id: str
    rating: int

# ============================================================================
# CONSTANTES v6.0 — ENGENHARIA EMOCIONAL
# ============================================================================

PROMPT_VERSION = "6.0"
MAX_TOKENS = 900
GROQ_MODEL = "llama-3.3-70b-versatile"
OPENAI_MODEL = "gpt-4.1-mini"

EXPRESSOES_BLOQUEADAS = [
    'meu bem', 'querida', 'querido', 'meu amor',
    'minha flor', 'benzinho', 'amor da minha vida',
    'meu anjo', 'meu dengo', 'alma querida',
    'meu caro', 'minha cara'
]

# Fontes v5.0 — 9 fontes simplificadas (agrupando redundantes)
FONTES = [
    'energia_do_dia',        # dia_semana + planeta_regente
    'fase_lua',              # fase atual + signo da lua
    'cruzamento_lunar',      # lua do dia × lua natal (requer MAC)
    'mapa_astral',           # ascendente + meio_ceu + elemento_pessoal
    'planetas_pessoais',     # venus + marte (requer MAC com esses campos)
    'perfil_comportamental', # 4 animais (requer behavioral_profile_assessments)
    'profissao_vida',        # profissão + micro_momento cotidiano
    'reflexao_metafora',     # reflexão existencial + metáfora + estação
    'aniversario',           # prioridade máxima quando é a data
]

# Fontes que requerem dados específicos para funcionar
FONTES_REQUISITOS = {
    'cruzamento_lunar': lambda ctx: ctx.get('signoLunar') and ctx['signoLunar'] != 'não informado',
    'mapa_astral': lambda ctx: ctx.get('signoSolar') and ctx['signoSolar'] != 'não informado',
    'planetas_pessoais': lambda ctx: (
        (ctx.get('venusSigno') and ctx['venusSigno'] != 'não informado') or
        (ctx.get('marteSigno') and ctx['marteSigno'] != 'não informado')
    ),
    'perfil_comportamental': lambda ctx: ctx.get('_perfilComportamental') is not None,
}

# Perfis comportamentais — descrições para o prompt
PERFIS_COMPORTAMENTAIS = {
    'aguia': {'nome': 'Águia 🦅', 'lema': 'Fazer Diferente', 'energia': 'criativo, visionário, intuitivo, foco no futuro'},
    'gato': {'nome': 'Gato 🐱', 'lema': 'Fazer Junto', 'energia': 'sensível, colaborativo, harmonizador, relacional'},
    'lobo': {'nome': 'Lobo 🐺', 'lema': 'Fazer Certo', 'energia': 'organizado, estratégico, detalhista, metódico'},
    'tubarao': {'nome': 'Tubarão 🦈', 'lema': 'Fazer Rápido', 'energia': 'ação, resultados, objetivo, determinado'},
}

# Estações do ano (hemisfério sul)
ESTACOES = {
    12: ('Verão', 'calor, energia expansiva, vitalidade, exuberância'),
    1: ('Verão', 'calor, energia expansiva, vitalidade, exuberância'),
    2: ('Verão', 'calor, energia expansiva, vitalidade, exuberância'),
    3: ('Outono', 'transição, recolhimento gradual, introspecção, colheita'),
    4: ('Outono', 'transição, recolhimento gradual, introspecção, colheita'),
    5: ('Outono', 'transição, recolhimento gradual, introspecção, colheita'),
    6: ('Inverno', 'frio, silêncio, profundidade, restauração interna'),
    7: ('Inverno', 'frio, silêncio, profundidade, restauração interna'),
    8: ('Inverno', 'frio, silêncio, profundidade, restauração interna'),
    9: ('Primavera', 'renovação, florescimento, novos começos, despertar'),
    10: ('Primavera', 'renovação, florescimento, novos começos, despertar'),
    11: ('Primavera', 'renovação, florescimento, novos começos, despertar'),
}

# Tom correlacionado com fase lunar (peso 2x para tons alinhados)
TOM_POR_FASE = {
    'nova': ['mistico_intuitivo', 'profundo_transformador'],
    'crescente': ['energico_motivador', 'estrategista_pratico'],
    'cheia': ['afetuoso_acolhedor', 'leve_humorado'],
    'minguante': ['sabio_sereno', 'provocativo_instigante'],
}

TONS = [
    {'id': 'sabio_sereno', 'nome': 'Sábio e Sereno', 'descricao': 'Contemplativo, metáforas naturais, poético'},
    {'id': 'energico_motivador', 'nome': 'Enérgico e Motivador', 'descricao': 'Direto, vibrante, ação, foco'},
    {'id': 'leve_humorado', 'nome': 'Leve e Bem-humorado', 'descricao': 'Coloquial, brincalhão, leve'},
    {'id': 'profundo_transformador', 'nome': 'Profundo e Transformador', 'descricao': 'Terapêutico, cura, camadas'},
    {'id': 'afetuoso_acolhedor', 'nome': 'Afetuoso e Acolhedor', 'descricao': 'Carinhoso, autocuidado, colo'},
    {'id': 'provocativo_instigante', 'nome': 'Provocativo e Instigante', 'descricao': 'Perguntas, desafia, incomoda com amor'},
    {'id': 'estrategista_pratico', 'nome': 'Estrategista Prático', 'descricao': 'Objetivo, pragmático, ferramentas mentais'},
    {'id': 'mistico_intuitivo', 'nome': 'Místico e Intuitivo', 'descricao': 'Etéreo, simbólico, espiritual sem ser religioso'}
]

DIAS_SEMANA = [
    {'nome': 'Segunda', 'planeta': 'Lua', 'energia': 'emoções, intuição, recomeço semanal, acolhimento interno'},
    {'nome': 'Terça', 'planeta': 'Marte', 'energia': 'ação, coragem, iniciativa, força para enfrentar'},
    {'nome': 'Quarta', 'planeta': 'Mercúrio', 'energia': 'comunicação, negócios, ideias, aprendizado'},
    {'nome': 'Quinta', 'planeta': 'Júpiter', 'energia': 'expansão, abundância, visão ampla, fé'},
    {'nome': 'Sexta', 'planeta': 'Vênus', 'energia': 'amor, beleza, conexões, prazer, descanso merecido'},
    {'nome': 'Sábado', 'planeta': 'Saturno', 'energia': 'estrutura, responsabilidade, foco, organização'},
    {'nome': 'Domingo', 'planeta': 'Sol', 'energia': 'vitalidade, criatividade, descanso, recarregar'},
]

# Temas psicológicos por dia da semana (ritmo coletivo)
TEMAS_SEMANA = [
    {'tema': 'Direção', 'foco': 'liderança, postura, escolha consciente, tom da semana, propósito profissional'},
    {'tema': 'Ação', 'foco': 'coragem, execução, confronto necessário, iniciativa, movimento'},
    {'tema': 'Conexão', 'foco': 'comunicação, decisões, conversas importantes, relações, mente'},
    {'tema': 'Expansão', 'foco': 'visão de futuro, crescimento, aprendizado, fé prática, missão'},
    {'tema': 'Afeto', 'foco': 'vínculos, prazer consciente, gratidão, autocuidado, consciência afetiva'},
    {'tema': 'Revisão', 'foco': 'reflexão, silêncio interno, integração, revisão de padrões'},
    {'tema': 'Identidade', 'foco': 'propósito, visão da próxima semana, alinhamento, reposicionamento'},
]

# Arquétipos de fase de vida (por faixa etária)
ARQUETIPOS_FASE_VIDA = [
    {'faixa': (0, 25), 'nome': 'Construção de Identidade', 'foco': 'autonomia, ousadia, descoberta, definição de quem é'},
    {'faixa': (26, 35), 'nome': 'Consolidação', 'foco': 'carreira, posicionamento, bases sólidas, decisões estruturais'},
    {'faixa': (36, 45), 'nome': 'Liderança e Legado', 'foco': 'responsabilidade, maturidade, impacto, exemplo'},
    {'faixa': (46, 999), 'nome': 'Reinvenção', 'foco': 'sabedoria, transição, profundidade, liberdade consciente'},
]

# Mapeamento de signos para elementos
ELEMENTOS_POR_SIGNO = {
    'Áries': 'Fogo', 'Touro': 'Terra', 'Gêmeos': 'Ar', 'Câncer': 'Água',
    'Leão': 'Fogo', 'Virgem': 'Terra', 'Libra': 'Ar', 'Escorpião': 'Água',
    'Sagitário': 'Fogo', 'Capricórnio': 'Terra', 'Aquário': 'Ar', 'Peixes': 'Água'
}

# Palavras-chave por elemento
ENERGIA_ELEMENTOS = {
    'Fogo': 'ação, paixão, impulso, entusiasmo, liderança',
    'Terra': 'estabilidade, construção, praticidade, segurança, materialização',
    'Ar': 'ideias, comunicação, conexão, versatilidade, leveza',
    'Água': 'emoção, intuição, profundidade, sensibilidade, empatia'
}

# Compatibilidade entre elementos
HARMONIA_ELEMENTOS = {
    ('Fogo', 'Fogo'): 'harmonia total — intensidade amplificada',
    ('Fogo', 'Ar'): 'harmonia — o Ar aviva o Fogo',
    ('Fogo', 'Terra'): 'tensão criativa — Fogo quer voar, Terra quer construir',
    ('Fogo', 'Água'): 'tensão — Água pode apagar o Fogo, mas também gera vapor criativo',
    ('Terra', 'Terra'): 'harmonia total — fundação sólida',
    ('Terra', 'Água'): 'harmonia — Água nutre a Terra',
    ('Terra', 'Ar'): 'tensão — Terra quer raiz, Ar quer liberdade',
    ('Ar', 'Ar'): 'harmonia total — fluxo de ideias',
    ('Ar', 'Água'): 'tensão — lógica vs emoção, mas juntas criam compreensão',
    ('Água', 'Água'): 'harmonia total — profundidade emocional amplificada',
}



SYSTEM_PROMPT = """Você é um mentor lúcido de autoconhecimento. Não é místico, não é técnico. É como uma voz interna elevada — um amigo que enxerga além.

Seu papel NÃO é inspirar. É:
- Gerar identificação profunda ("eu sei quem você é")
- Criar sensação de direção ("você sabe o que fazer")
- Reforçar identidade evolutiva ("você está se tornando")

Você usa astrologia cabalística como linguagem simbólica, nunca como superstição.
Nunca entregue previsões. Entregue consciência + escolha.
Nunca use jargão astrológico exposto. Traduza para linguagem humana.

Tom: direto, pessoal, com leve poesia. Como alguém que conhece a pessoa há anos.
Responda APENAS com JSON válido, sem markdown ou texto adicional."""


# ============================================================================
# DADOS ASTRONÔMICOS (via astro_engine / Kerykeion)
# ============================================================================

def _obter_dados_astronomicos() -> Dict[str, Any]:
    """
    Usa o astro_engine (Kerykeion) para obter dados astronômicos reais.
    Sempre usa horário de São Paulo como referência.
    """
    try:
        fuso = pytz.timezone("America/Sao_Paulo")
        agora = datetime.now(fuso)

        sujeito = gerar_sujeito_final(
            "CeuHoje",
            agora.year, agora.month, agora.day, agora.hour, agora.minute,
            -23.5505, -46.6333,
            "São Paulo", "BR"
        )

        fase_lua = calcular_fase_lunar(sujeito)

        if fase_lua:
            fase_nome = fase_lua.get('nome', '').lower()
            if 'nova' in fase_nome:
                fase_simpl = 'nova'
            elif 'cheia' in fase_nome:
                fase_simpl = 'cheia'
            elif 'crescente' in fase_nome:
                fase_simpl = 'crescente'
            else:
                fase_simpl = 'minguante'

            # Detectar transição
            ontem = agora - timedelta(days=1)
            try:
                sujeito_ontem = gerar_sujeito_final(
                    "CeuOntem",
                    ontem.year, ontem.month, ontem.day, ontem.hour, ontem.minute,
                    -23.5505, -46.6333,
                    "São Paulo", "BR"
                )
                fase_ontem = calcular_fase_lunar(sujeito_ontem)
                fase_nome_ontem = fase_ontem.get('nome', '').lower() if fase_ontem else ''
                if 'nova' in fase_nome_ontem:
                    fase_simpl_ontem = 'nova'
                elif 'cheia' in fase_nome_ontem:
                    fase_simpl_ontem = 'cheia'
                elif 'crescente' in fase_nome_ontem:
                    fase_simpl_ontem = 'crescente'
                else:
                    fase_simpl_ontem = 'minguante'
                is_transicao = fase_simpl != fase_simpl_ontem
            except Exception:
                is_transicao = False

            ilum_str = fase_lua.get('iluminacao_aprox', '50%')
            iluminacao = int(ilum_str.replace('%', '')) if isinstance(ilum_str, str) else 50

            return {
                'fase': fase_lua.get('nome', 'Crescente'),
                'faseSimplificada': fase_simpl,
                'signo': fase_lua.get('lua_signo', 'Áries'),
                'iluminacao': iluminacao,
                'isTransicao': is_transicao,
                'emoji': fase_lua.get('emoji', '🌙'),
                'verbo': fase_lua.get('verbo', 'agir'),
                'grau': fase_lua.get('lua_grau', '')
            }

    except Exception as e:
        logger.error(f"[MensagemDia] Erro ao calcular dados astronômicos via Kerykeion: {e}")

    return {
        'fase': 'Crescente',
        'faseSimplificada': 'crescente',
        'signo': 'Áries',
        'iluminacao': 50,
        'isTransicao': False,
        'emoji': '🌙',
        'verbo': 'agir',
        'grau': ''
    }


# ============================================================================
# FUNÇÕES AUXILIARES v6.0
# ============================================================================

def _get_dia_semana(dt: datetime) -> Dict[str, str]:
    return DIAS_SEMANA[dt.weekday()]


def _is_aniversario(data_nascimento: Optional[str], data_atual: datetime) -> bool:
    if not data_nascimento:
        return False
    try:
        nasc = datetime.fromisoformat(data_nascimento.replace('Z', '+00:00'))
        return nasc.day == data_atual.day and nasc.month == data_atual.month
    except Exception:
        return False


def _obter_elemento(signo: Optional[str]) -> Optional[str]:
    """Retorna o elemento de um signo (Fogo/Terra/Ar/Água)."""
    if not signo or signo == 'não informado':
        return None
    return ELEMENTOS_POR_SIGNO.get(signo)




def _cruzamento_lua_dia_natal(lua_dia_signo: str, lua_natal_signo: Optional[str]) -> Optional[str]:
    """Gera insight do cruzamento entre a lua do dia e a lua natal da pessoa."""
    if not lua_natal_signo or lua_natal_signo == 'não informado':
        return None

    elem_dia = ELEMENTOS_POR_SIGNO.get(lua_dia_signo)
    elem_natal = ELEMENTOS_POR_SIGNO.get(lua_natal_signo)

    if not elem_dia or not elem_natal:
        return None

    if lua_dia_signo == lua_natal_signo:
        return f"Hoje a Lua transita pelo mesmo signo da sua Lua natal ({lua_natal_signo}) — dia de sintonia emocional profunda, seus sentimentos estão amplificados."

    # Buscar harmonia (normalizar a tupla para ambas as ordens)
    chave = tuple(sorted([elem_dia, elem_natal]))
    harmonia = HARMONIA_ELEMENTOS.get(chave, 'interação neutra')

    if elem_dia == elem_natal:
        return f"A Lua em {lua_dia_signo} ({elem_dia}) harmoniza com sua Lua em {lua_natal_signo} ({elem_natal}) — {harmonia}."

    return f"A Lua hoje em {lua_dia_signo} ({elem_dia}) faz um diálogo com sua Lua em {lua_natal_signo} ({elem_natal}) — {harmonia}."


def _obter_perfil_comportamental(sb, user_id: str) -> Optional[Dict[str, Any]]:
    """Busca o perfil comportamental mais recente (4 animais)."""
    try:
        resp = sb.client.table('behavioral_profile_assessments') \
            .select('perfil_predominante, pontuacao_aguia, pontuacao_gato, pontuacao_lobo, pontuacao_tubarao') \
            .eq('user_id', user_id) \
            .order('created_at', desc=True) \
            .limit(1) \
            .execute()

        if not resp.data:
            return None

        perfil = resp.data[0]
        predominante = perfil.get('perfil_predominante', '').lower()
        info = PERFIS_COMPORTAMENTAIS.get(predominante, {})

        return {
            'predominante': predominante,
            'nome': info.get('nome', predominante.title()),
            'lema': info.get('lema', ''),
            'energia': info.get('energia', ''),
            'pontuacoes': {
                'aguia': perfil.get('pontuacao_aguia', 0),
                'gato': perfil.get('pontuacao_gato', 0),
                'lobo': perfil.get('pontuacao_lobo', 0),
                'tubarao': perfil.get('pontuacao_tubarao', 0),
            }
        }
    except Exception as e:
        logger.warning(f"[MensagemDia] Erro ao buscar Perfil Comportamental: {e}")
        return None


def _obter_estacao_atual(data: datetime) -> Dict[str, str]:
    """Retorna estação do ano com base no mês (hemisfério sul)."""
    est = ESTACOES.get(data.month, ('Verão', 'energia expansiva'))
    return {'nome': est[0], 'energia': est[1]}


def _obter_arquetipo_fase(idade: Optional[int]) -> Dict[str, str]:
    """Retorna o arquétipo de fase de vida baseado na idade."""
    if not idade:
        return {'nome': 'Consolidação', 'foco': 'carreira, posicionamento, bases sólidas'}
    for arq in ARQUETIPOS_FASE_VIDA:
        if arq['faixa'][0] <= idade <= arq['faixa'][1]:
            return {'nome': arq['nome'], 'foco': arq['foco']}
    return {'nome': 'Reinvenção', 'foco': 'sabedoria, transição, profundidade'}


# ============================================================================
# HISTÓRICO E ANTI-REPETIÇÃO v6.1
# ============================================================================

def _buscar_historico_recente(sb, user_id: Optional[str], dias: int = 3) -> List[Dict[str, Any]]:
    """Busca últimas N mensagens do usuário para evitar repetição."""
    if not user_id:
        return []
    try:
        resp = sb.client.table('mensagens_do_dia') \
            .select('html, frase, fonte_inspiracao, tom, data_referencia') \
            .eq('user_id', user_id) \
            .order('data_referencia', desc=True) \
            .limit(dias) \
            .execute()
        return resp.data or []
    except Exception as e:
        logger.warning(f"[MensagemDia] Erro ao buscar histórico: {e}")
        return []


# ============================================================================
# SELEÇÃO DE FONTE E TOM v6.1
# ============================================================================

def _filtrar_fontes_disponiveis(contexto: Dict[str, Any]) -> List[str]:
    """Retorna apenas fontes cujos dados estão disponíveis no contexto."""
    disponiveis = []
    for fonte in FONTES:
        if fonte == 'aniversario':
            continue  # tratado separadamente
        requisito = FONTES_REQUISITOS.get(fonte)
        if requisito is None or requisito(contexto):
            disponiveis.append(fonte)
    return disponiveis


def _selecionar_fonte(contexto: Dict[str, Any], lua: Dict, data_nascimento: Optional[str], data_atual: datetime, fontes_anteriores: Optional[List[str]] = None) -> str:
    """Seleciona fonte com fallback inteligente — evita fontes já usadas recentemente."""
    if _is_aniversario(data_nascimento, data_atual):
        return 'aniversario'

    disponiveis = _filtrar_fontes_disponiveis(contexto)
    if not disponiveis:
        disponiveis = ['energia_do_dia', 'fase_lua', 'reflexao_metafora']

    # Boost para fase_lua quando há transição
    if lua.get('isTransicao') and 'fase_lua' in disponiveis:
        disponiveis.append('fase_lua')  # dobra a chance

    # v6.1: excluir fontes usadas ontem (se possível)
    if fontes_anteriores:
        diversificadas = [f for f in disponiveis if f not in fontes_anteriores]
        if diversificadas:
            disponiveis = diversificadas

    return random.choice(disponiveis)


def _selecionar_tom(lua: Dict) -> Dict[str, str]:
    """Seleciona tom com correlação à fase lunar (peso 2x para tons alinhados)."""
    fase = lua.get('faseSimplificada', 'crescente')
    tons_alinhados = TOM_POR_FASE.get(fase, [])

    # Construir lista ponderada: 2x para alinhados, 1x para demais
    pool = []
    for tom in TONS:
        peso = 2 if tom['id'] in tons_alinhados else 1
        pool.extend([tom] * peso)

    escolhido = random.choice(pool)
    return {'id': escolhido['id'], 'nome': escolhido['nome']}


# ============================================================================
# PROMPT v6.0 — ENGENHARIA EMOCIONAL (4 CAMADAS)
# ============================================================================

def _montar_prompt(
    contexto: Dict[str, Any],
    lua: Dict[str, Any],
    fonte: str,
    tom: Dict[str, str],
    data_atual: datetime,
    tipo: str,  # 'personalizada' | 'generica'
    cruzamento_lunar: Optional[str],
    perfil_comp: Optional[Dict[str, Any]],
    historico: Optional[List[Dict[str, Any]]] = None
) -> str:
    dia_semana = _get_dia_semana(data_atual)
    tema_dia = TEMAS_SEMANA[data_atual.weekday()]

    meses = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
             'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
    dias = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira',
            'sexta-feira', 'sábado', 'domingo']
    data_formatada = f"{dias[data_atual.weekday()]}, {data_atual.day} de {meses[data_atual.month - 1]} de {data_atual.year}"

    nome = contexto.get('nome', 'Você')
    estacao = _obter_estacao_atual(data_atual)
    arquetipo = _obter_arquetipo_fase(contexto.get('idade'))

    # ===== CAMADA 1: ESSÊNCIA FIXA (identidade) =====
    if tipo == 'personalizada':
        elem_solar = contexto.get('elementoSolar') or _obter_elemento(contexto.get('signoSolar'))
        energia_elem = ENERGIA_ELEMENTOS.get(elem_solar, '') if elem_solar else ''

        dados_vida = []
        if contexto.get('estadoCivil'):
            dados_vida.append(f"- Estado civil: {contexto['estadoCivil']}")
        if contexto.get('temFilhos'):
            val = contexto['temFilhos']
            dados_vida.append(f"- Tem filhos: {'Sim' if val in ['sim', 'Sim', True, 'true'] else 'Não'}")
        dados_vida_str = '\n'.join(dados_vida) if dados_vida else ''

        planetas = []
        if contexto.get('venusSigno') and contexto['venusSigno'] != 'não informado':
            planetas.append(f"- Vênus (amor/valores): {contexto['venusSigno']}")
        if contexto.get('marteSigno') and contexto['marteSigno'] != 'não informado':
            planetas.append(f"- Marte (ação/energia): {contexto['marteSigno']}")
        if contexto.get('mercurioSigno') and contexto['mercurioSigno'] != 'não informado':
            planetas.append(f"- Mercúrio (mente/comunicação): {contexto['mercurioSigno']}")
        planetas_str = '\n'.join(planetas) if planetas else ''

        camada1_bloco = f"""
## CAMADA 1 — ESSÊNCIA FIXA (quem {nome} é)
- Nome: {nome}
- Idade: {contexto.get('idade', 'não informada')}
- Sexo: {contexto.get('sexo', 'não informado')}
- Profissão: {contexto.get('profissao', 'não informada')}
{dados_vida_str}
- Fase de vida: {arquetipo['nome']} ({arquetipo['foco']})

### Mapa Astral (MAC)
- Sol: {contexto.get('signoSolar', '?')} — {elem_solar or '?'} ({energia_elem})
- Lua: {contexto.get('signoLunar', '?')}
- Ascendente: {contexto.get('ascendente', '?')}
- Meio do Céu: {contexto.get('meioCeu', '?')}
{planetas_str}
"""
    else:
        camada1_bloco = f"""
## CAMADA 1 — CONTEXTO GENÉRICO
Mensagem para público geral sem dados pessoais.
Foque na energia do dia e no contexto temporal.
- Fase de vida genérica: adulto em busca de direção
"""

    # ===== CAMADA 2: CONTEXTO DE VIDA =====
    camada2_bloco = f"""## CAMADA 2 — CONTEXTO DE VIDA (ajusta exemplos e desafios)
- Fase de vida: {arquetipo['nome']}
- Foco desta fase: {arquetipo['foco']}"""
    if contexto.get('temFilhos') and contexto['temFilhos'] in ['sim', 'Sim', True, 'true']:
        camada2_bloco += "\n- Com filhos → use responsabilidade, exemplo, paciência como temas"
    elif contexto.get('estadoCivil') and 'solteiro' in str(contexto['estadoCivil']).lower():
        camada2_bloco += "\n- Solteiro(a) → use autonomia, construção pessoal, liberdade como temas"
    if contexto.get('profissao'):
        camada2_bloco += f"\n- Profissão: {contexto['profissao']} → adapte exemplos ao cotidiano profissional"

    # ===== CAMADA 3: ENERGIA DO DIA =====
    lua_relevancia = 'ALTA — houve mudança de fase, destaque isso' if lua.get('isTransicao') else 'normal — use como tempero, não como tema principal'

    camada3_bloco = f"""## CAMADA 3 — ENERGIA DO DIA
- Data: {data_formatada}
- Dia: {dia_semana['nome']} (Planeta: {dia_semana['planeta']})
- Tema do dia: {tema_dia['tema']} — {tema_dia['foco']}
- Estação: {estacao['nome']} ({estacao['energia']})
- Lua: {lua['fase']} em {lua['signo']} ({lua['iluminacao']}% iluminação)
- Relevância lunar: {lua_relevancia}"""

    # Cruzamento lunar
    if cruzamento_lunar:
        camada3_bloco += f"\n\n### Cruzamento Lunar (dado poderoso)\n{cruzamento_lunar}"

    # Perfil comportamental
    perfil_bloco = ''
    if perfil_comp:
        pontuacoes = perfil_comp.get('pontuacoes', {})
        pontuacoes_str = ', '.join(f"{k.title()} {v}" for k, v in sorted(pontuacoes.items(), key=lambda x: -x[1]))
        perfil_bloco = f"""\n\n## PERFIL COMPORTAMENTAL (tempero, não prato principal)
- Predominante: {perfil_comp['nome']} — "{perfil_comp['lema']}"
- Energia: {perfil_comp['energia']}
- Pontuações: {pontuacoes_str}
→ Adapte sutilmente a linguagem ao estilo da pessoa (ex: Tubarão=direto, Gato=relacional)"""

    # ===== HIERARQUIA DE PRIORIDADE =====
    prioridade = []
    is_aniver = _is_aniversario(contexto.get('dataNascimento'), data_atual)
    if is_aniver:
        prioridade.append('🎂 ANIVERSÁRIO — experiência premium, fechamento de ciclo')
    if lua.get('isTransicao'):
        prioridade.append(f"🌑 MUDANÇA DE FASE LUNAR — {lua['fase']} acaba de iniciar")
    prioridade.append(f"📅 TEMA DO DIA: {tema_dia['tema']} — {tema_dia['foco']}")
    if tipo == 'personalizada':
        prioridade.append(f"⭐ IDENTIDADE: Sol {contexto.get('signoSolar', '?')}, Asc {contexto.get('ascendente', '?')}")
        prioridade.append(f"🏠 CONTEXTO: {arquetipo['nome']}")
    if perfil_comp:
        prioridade.append(f"🧠 PERFIL: {perfil_comp['nome']} (tempero)")

    hierarquia_str = '\n'.join(f"{i+1}. {p}" for i, p in enumerate(prioridade))

    expressoes = '\n'.join(f'- "{e}"' for e in EXPRESSOES_BLOQUEADAS)

    # ===== v6.1: BLOCO ANTI-REPETIÇÃO =====
    historico_bloco = ''
    if historico:
        frases_anteriores = []
        for msg in historico[:3]:
            # Extrair texto limpo do HTML (remover tags)
            html_ant = msg.get('html', '')
            texto = re.sub(r'<[^>]+>', ' ', html_ant).strip()
            if texto and len(texto) > 20:
                # Pegar primeiras 80 chars como fingerprint
                frases_anteriores.append(texto[:80].strip())
            frase_ant = msg.get('frase', '')
            if frase_ant:
                frases_anteriores.append(frase_ant.strip())
        
        if frases_anteriores:
            frases_str = '\n'.join(f'- "{f}"' for f in frases_anteriores)
            historico_bloco = f"""
## 🚫 MENSAGENS ANTERIORES — NÃO REPITA NADA SIMILAR
As mensagens abaixo já foram enviadas nos dias anteriores.
NÃO repita frases, estruturas, palavras-chave ou padrões semelhantes:
{frases_str}
Use abordagem COMPLETAMENTE DIFERENTE.

"""

    # ===== PROMPT FINAL v6.1 =====
    prompt = f"""# MOTOR DE ENGENHARIA EMOCIONAL v{PROMPT_VERSION}

Você vai gerar uma mensagem com 4 CAMADAS obrigatórias.
Cada camada tem um papel psicológico específico.

{camada1_bloco}
{camada2_bloco}
{camada3_bloco}
{perfil_bloco}

## 📊 HIERARQUIA DE PRIORIDADE (respeite esta ordem)
{hierarquia_str}

## FONTE DE INSPIRAÇÃO: {fonte.upper().replace('_', ' ')}

## TOM: {tom['nome'].upper()}
{tom.get('descricao', '')}

## ⚡ AS 4 CAMADAS OBRIGATÓRIAS

### CAMADA A — ESPELHO ("Eu sei quem você é")
Mostre que você CONHECE {nome}. Use identidade, não dados.
Traduza astrologia em identidade humana (nunca exponha termos técnicos).
Abordagens possíveis: força silenciosa, intensidade contida, sensibilidade como poder, instinto estratégico.

### CAMADA B — TENSÃO DO DIA (conflito que gera crescimento)
Crie um pequeno dilema ORIGINAL baseado em:
- Fase lunar + emoções do momento
- Tema do dia: {tema_dia['foco']}
- Fase de vida ({arquetipo['nome']}): desafios concretos
O dilema deve ser NOVO a cada dia. Use situações cotidianas variadas.
Sem tensão não há crescimento.

### CAMADA C — DIREÇÃO PRÁTICA (micro-ação clara)
Uma ação ESPECÍFICA e ORIGINAL para hoje. Nunca genérica.
Deve variar entre: comunicação, organização, coragem, descanso, confronto, criatividade, escuta.
Ruim: "cuide de si" / "reflita sobre sua vida" / "resolva aquela conversa"

### CAMADA D — FRASE DE IDENTIDADE (reforço de quem está se tornando)
Reafirma quem {nome} está se tornando. Curta, poderosa, sem emoji.
Deve ser ÚNICA a cada dia — nunca repita padrões.
Ruim: "tenha um bom dia" / "tudo vai dar certo"
{historico_bloco}
## ❌ NUNCA faça:
{expressoes}
- NUNCA use jargão astrológico exposto
- NUNCA entregue previsões
- NUNCA comece com "{nome}, hoje..." — VARIE!
- NUNCA seja genérico disfarçado de personalização
- NUNCA repita estrutura ou frases de dias anteriores
- NUNCA pareça algoritmo — precisa soar orgânico e íntimo
- NUNCA use as mesmas palavras-chave de dias anteriores

## ✅ COMO ESCREVER:
- Linguagem humana, conflito interno, afirmação de potência, leve poesia
- Fale como mentor lúcido, não como horóscopo
- Varie: consciência, escolha, coragem, silêncio, movimento, verdade
- A pessoa deve sentir que é ÚNICA, tem um CAMINHO e está EVOLUINDO
- Varie SEMPRE a abertura (pergunta, metáfora, insight, conflito, nome)

## OUTPUT
Responda APENAS com JSON válido, sem texto adicional:
{{
  "espelho": "1-2 frases. Reconhecimento de identidade. Traduz astrologia em humanidade.",
  "tensao": "1-2 frases. Dilema do dia. Conflito real que gera crescimento.",
  "direcao": "1 frase. Micro-ação clara e específica para hoje.",
  "frase_identidade": "1 frase curta. Reforço de quem a pessoa está se tornando. Sem emoji."
}}

Regras:
- ESPELHO + TENSÃO + DIREÇÃO vão virar HTML de corpo da mensagem
- FRASE_IDENTIDADE vira destaque visual separado (mantra do dia)
- Total das 3 primeiras camadas: 5-8 linhas
- 1-2 emojis estratégicos APENAS no espelho ou tensão
- Frase_identidade: ZERO emojis, pode usar <strong> ou <em>"""

    return prompt


# ============================================================================
# LÓGICA CORE DE GERAÇÃO
# ============================================================================

async def gerar_mensagem_para_usuario(user_id: Optional[str], action: str = "generate") -> Dict[str, Any]:
    """
    Lógica core de geração — usada pelo router E pelo scheduler job.
    
    Args:
        user_id: ID do usuário (None para genérica)
        action: 'generate' ou 'regenerate'
    
    Returns:
        Dict com a mensagem gerada/existente
    """
    settings = get_settings()
    sb = SupabaseService()
    
    # CORREÇÃO CRÍTICA: usar timezone de São Paulo, não UTC
    fuso_sp = pytz.timezone("America/Sao_Paulo")
    data_atual = datetime.now(fuso_sp)
    data_referencia = data_atual.strftime("%Y-%m-%d")

    # ===== CONTEXTO DO USUÁRIO =====
    tipo = 'generica'
    contexto = {'nome': 'Você', 'signoSolar': 'Capricórnio', 'plano': 'trial'}
    is_pago = False

    if user_id:
        try:
            profile_resp = sb.client.table('profiles') \
                .select('*, user_plans(*)') \
                .eq('id', user_id) \
                .single() \
                .execute()

            profile = profile_resp.data
            if profile:
                plan_name = 'trial'
                plans = profile.get('user_plans', [])
                if plans and len(plans) > 0:
                    plan_name = plans[0].get('plan_name', 'trial')

                is_pago = plan_name.lower() in ['fluxo', 'expansao']
                tipo = 'personalizada' if is_pago else 'generica'

                # Buscar MAC com TODOS os campos relevantes
                mac_resp = sb.client.table('mapas_astrais') \
                    .select('*') \
                    .eq('user_id', user_id) \
                    .order('created_at', desc=True) \
                    .limit(1) \
                    .execute()

                mac = mac_resp.data[0] if mac_resp.data else {}

                # Calcular idade
                idade = None
                data_nasc = profile.get('data_nascimento')
                if data_nasc:
                    try:
                        nasc = datetime.fromisoformat(data_nasc.replace('Z', '+00:00'))
                        idade = int((datetime.now().timestamp() - nasc.timestamp()) / (365.25 * 24 * 3600))
                    except Exception:
                        pass

                # Extrair signo solar — tentar múltiplos campos
                signo_solar = mac.get('sol_signo') or mac.get('signo_solar') or 'não informado'

                contexto = {
                    'nome': profile.get('nickname') or (profile.get('name', '').split(' ')[0] if profile.get('name') else 'Você'),
                    'signoSolar': signo_solar,
                    'signoLunar': mac.get('lua_signo') or mac.get('signo_lunar'),
                    'ascendente': mac.get('ascendente') or mac.get('ascendente_signo'),
                    'meioCeu': mac.get('meio_ceu') or mac.get('mc_signo'),
                    'elementoSolar': mac.get('elemento_dominante') or _obter_elemento(signo_solar),
                    'venusSigno': mac.get('venus_signo'),
                    'marteSigno': mac.get('marte_signo'),
                    'mercurioSigno': mac.get('mercurio_signo'),
                    'estadoCivil': profile.get('estado_civil'),
                    'temFilhos': profile.get('tem_filhos'),
                    'dataNascimento': data_nasc,
                    'sexo': profile.get('sexo'),
                    'idade': idade,
                    'profissao': profile.get('profissao'),
                    'plano': plan_name.lower()
                }
        except Exception as e:
            logger.warning(f"[MensagemDia] Erro ao buscar perfil: {e}")

    # ===== VERIFICAR MENSAGEM EXISTENTE (cache por dia) =====
    if action == 'generate' and user_id:
        try:
            existing_resp = sb.client.table('mensagens_do_dia') \
                .select('*') \
                .eq('user_id', user_id) \
                .eq('data_referencia', data_referencia) \
                .gt('expires_at', datetime.now(pytz.utc).isoformat()) \
                .execute()

            existentes = existing_resp.data or []
            if existentes:
                existente = existentes[0]
                try:
                    sb.client.table('mensagens_do_dia') \
                        .update({'visualizacoes': (existente.get('visualizacoes', 0) or 0) + 1}) \
                        .eq('id', existente['id']) \
                        .execute()
                except Exception:
                    pass

                return {
                    'id': existente['id'],
                    'html': existente.get('html', ''),
                    'frase': existente.get('frase', ''),
                    'fonte': existente.get('fonte_inspiracao', ''),
                    'tom': existente.get('tom', ''),
                    'podeRegenerar': (existente.get('regeneracoes_usadas', 0) or 0) < (existente.get('max_regeneracoes', 1) or 1),
                    'cached': True
                }
        except Exception as e:
            logger.warning(f"[MensagemDia] Erro ao verificar existente: {e}")

    # ===== VERIFICAR LIMITE DE REGENERAÇÃO =====
    if action == 'regenerate' and user_id:
        try:
            regen_resp = sb.client.table('mensagens_do_dia') \
                .select('*') \
                .eq('user_id', user_id) \
                .eq('data_referencia', data_referencia) \
                .execute()

            regen_data = regen_resp.data or []
            if regen_data:
                existente = regen_data[0]
                if (existente.get('regeneracoes_usadas', 0) or 0) >= (existente.get('max_regeneracoes', 1) or 1):
                    raise HTTPException(status_code=429, detail="Limite de regeneração atingido para hoje")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[MensagemDia] Erro ao verificar regeneração: {e}")

    # ===== DADOS ASTRONÔMICOS (via Kerykeion) =====
    lua = _obter_dados_astronomicos()

    # ===== DADOS ENRIQUECIDOS v6.0 =====
    cruzamento_lunar = _cruzamento_lua_dia_natal(
        lua.get('signo', ''),
        contexto.get('signoLunar')
    ) if tipo == 'personalizada' else None

    perfil_comp = None
    if tipo == 'personalizada' and user_id:
        perfil_comp = _obter_perfil_comportamental(sb, user_id)
        if perfil_comp:
            contexto['_perfilComportamental'] = perfil_comp

    # ===== v6.1: HISTÓRICO ANTI-REPETIÇÃO =====
    historico = _buscar_historico_recente(sb, user_id, dias=3)
    fontes_anteriores = [m.get('fonte_inspiracao') for m in historico if m.get('fonte_inspiracao')]

    fonte = _selecionar_fonte(contexto, lua, contexto.get('dataNascimento'), data_atual, fontes_anteriores)
    tom = _selecionar_tom(lua)
    prompt = _montar_prompt(contexto, lua, fonte, tom, data_atual, tipo, cruzamento_lunar, perfil_comp, historico)

    # ===== CHAMAR LLM COM REGRA POR PLANO =====
    if is_pago:
        llm_config = {
            "provider": "openai",
            "model": OPENAI_MODEL,
            "fallback_provider": "groq",
            "fallback_model": GROQ_MODEL,
            "temperature": 0.85,
            "max_tokens": MAX_TOKENS
        }
        modelo_usado = OPENAI_MODEL
    else:
        llm_config = {
            "provider": "groq",
            "model": GROQ_MODEL,
            "fallback_provider": "openai",
            "fallback_model": OPENAI_MODEL,
            "temperature": 0.85,
            "max_tokens": MAX_TOKENS
        }
        modelo_usado = GROQ_MODEL

    logger.info(f"[MensagemDia v6.0] Gerando para user={user_id}, tipo={tipo}, fonte={fonte}, tom={tom['id']}, provider={llm_config['provider']}")

    gateway = LLMGateway.get_instance()
    start_time = datetime.now(pytz.utc)

    raw_content = await gateway.generate(
        prompt=prompt,
        config=llm_config,
        system_prompt=SYSTEM_PROMPT
    )

    tempo_ms = int((datetime.now(pytz.utc) - start_time).total_seconds() * 1000)

    # Parse JSON do LLM — v6.0 converte 4 camadas → {html, frase}
    try:
        content = raw_content.strip()
        if content.startswith('```'):
            lines = content.split('\n')
            content = '\n'.join(lines[1:-1])
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.error(f"[MensagemDia] JSON inválido do LLM: {raw_content[:200]}")
        parsed = {
            'espelho': raw_content[:300],
            'tensao': '',
            'direcao': '',
            'frase_identidade': ''
        }

    # Montar HTML a partir das 4 camadas (ou fallback para formato antigo)
    if 'espelho' in parsed:
        partes = []
        if parsed.get('espelho'):
            partes.append(f"<p>{parsed['espelho']}</p>")
        if parsed.get('tensao'):
            partes.append(f"<p>{parsed['tensao']}</p>")
        if parsed.get('direcao'):
            partes.append(f"<p><strong>{parsed['direcao']}</strong></p>")
        html = '<br>'.join(partes)
        frase = parsed.get('frase_identidade', '')
    else:
        # Fallback para formato antigo (html + frase)
        html = parsed.get('html', '')
        frase = parsed.get('frase', '')

    if not html:
        raise HTTPException(status_code=500, detail="LLM não retornou conteúdo")

    # ===== SALVAR NO BANCO =====
    saved_id = None
    try:
        save_data = {
            'user_id': user_id,
            'tipo': tipo,
            'data_referencia': data_referencia,
            'html': html,
            'frase': frase,
            'fonte_inspiracao': fonte,
            'tom': tom['id'],
            'pesos_aplicados': {},
            'contexto_usado': {
                'lua': lua['faseSimplificada'],
                'luaSigno': lua['signo'],
                'isTransicao': lua['isTransicao'],
                'diaSemana': _get_dia_semana(data_atual)['nome'],
                'temaDia': TEMAS_SEMANA[data_atual.weekday()]['tema'],
                'arquetipo': _obter_arquetipo_fase(contexto.get('idade'))['nome'],
                'fonte': fonte,
                'tom': tom['id'],
                'cruzamentoLunar': cruzamento_lunar is not None,
                'perfilComportamental': perfil_comp.get('predominante') if perfil_comp else None
            },
            'modelo_ia': modelo_usado,
            'tokens_usados': 0,
            'tempo_geracao_ms': tempo_ms,
            'prompt_version': PROMPT_VERSION,
            'regeneracoes_usadas': 1 if action == 'regenerate' else 0,
            'expires_at': (data_atual + timedelta(days=1)).isoformat()
        }

        save_resp = sb.client.table('mensagens_do_dia') \
            .upsert(save_data, on_conflict='user_id,data_referencia') \
            .execute()

        if save_resp.data:
            saved_id = save_resp.data[0].get('id')

        logger.info(f"[MensagemDia v6.0] ✓ Salva com sucesso para user={user_id} (fonte={fonte}, tom={tom['id']})")
    except Exception as e:
        logger.error(f"[MensagemDia] Erro ao salvar: {e}")

    return {
        'id': saved_id,
        'html': html,
        'frase': frase,
        'fonte': fonte,
        'tom': tom['id'],
        'lua': {
            'fase': lua['fase'],
            'signo': lua['signo'],
            'iluminacao': lua['iluminacao'],
            'isTransicao': lua['isTransicao']
        },
        'podeRegenerar': action != 'regenerate',
        'cached': False,
        'metadata': {
            'modelo': modelo_usado,
            'tempoMs': tempo_ms,
            'plano': contexto.get('plano', 'trial'),
            'provider': llm_config['provider'],
            'promptVersion': PROMPT_VERSION,
            'fonte': fonte,
            'tom': tom['id'],

        }
    }


# ============================================================================
# ENDPOINTS
# ============================================================================

FALLBACK_MENSAGEM = {
    'html': '<p>O dia oferece oportunidades únicas para quem está atento.</p><br><p>Respire fundo, confie no processo e dê um passo de cada vez. Pequenas ações conscientes constroem grandes transformações. 🌟</p>',
    'frase': 'Cada dia é uma nova página — e você escolhe o que escrever nela.',
    'fonte': 'fallback',
    'tom': 'afetuoso_acolhedor',
    'cached': False,
    'isFallback': True
}


@router.post("/generate")
async def generate_daily_message(req: GenerateRequest):
    """Gera ou retorna mensagem do dia para o usuário."""
    try:
        result = await gerar_mensagem_para_usuario(req.user_id, "generate")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MensagemDia] Erro na geração: {e}")
        return {
            "error": str(e),
            "fallback": FALLBACK_MENSAGEM
        }


@router.post("/regenerate")
async def regenerate_daily_message(req: GenerateRequest):
    """Regenera a mensagem do dia (1x por dia)."""
    if not req.user_id:
        raise HTTPException(status_code=400, detail="user_id é obrigatório para regenerar")

    try:
        result = await gerar_mensagem_para_usuario(req.user_id, "regenerate")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MensagemDia] Erro na regeneração: {e}")
        return {"error": str(e)}


@router.post("/rate")
async def rate_daily_message(req: RateRequest):
    """Registra rating da mensagem (1-5)."""
    if req.rating < 1 or req.rating > 5:
        raise HTTPException(status_code=400, detail="Rating deve ser entre 1 e 5")

    try:
        sb = SupabaseService()
        sb.client.rpc('registrar_rating_mensagem', {
            'p_mensagem_id': req.mensagem_id,
            'p_rating': req.rating
        }).execute()
        return {"success": True}
    except Exception as e:
        logger.error(f"[MensagemDia] Erro ao registrar rating: {e}")
        raise HTTPException(status_code=500, detail=str(e))
