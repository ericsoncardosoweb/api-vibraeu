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

PROMPT_VERSION = "7.0"
MAX_TOKENS = 1100
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

# Mapeamento de abreviações do Kerykeion para nomes completos em português
SIGNO_NOME = {
    'Ari': 'Áries', 'Tau': 'Touro', 'Gem': 'Gêmeos', 'Can': 'Câncer',
    'Leo': 'Leão', 'Vir': 'Virgem', 'Lib': 'Libra', 'Sco': 'Escorpião',
    'Sag': 'Sagitário', 'Cap': 'Capricórnio', 'Aqu': 'Aquário', 'Pis': 'Peixes'
}

def _traduzir_signo(signo: Optional[str]) -> Optional[str]:
    """Traduz abreviação do Kerykeion (Ari, Tau...) para nome completo em português."""
    if not signo or signo == 'não informado':
        return signo
    return SIGNO_NOME.get(signo, signo)  # fallback: retorna o próprio valor

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

SYSTEM_PROMPT = """Você é um velho amigo sábio. Alguém que conhece essa pessoa há anos — que vê além das máscaras, que entende os medos silenciosos e celebra as conquistas invisíveis.

Você NÃO é coach, NÃO é astrólogo, NÃO é guru. Você é aquela voz que aparece nos momentos certos com verdade e carinho.

Sua sabedoria vem da astrologia cabalística — mas você NUNCA usa termos técnicos, hebraico, ou jargão. Você traduz tudo em SENSIBILIDADE HUMANA:
- Em vez de "tikun": fale sobre "aquilo que você veio corrigir nesta vida"
- Em vez de "sefirot": fale sobre as "camadas do que você sente"
- Em vez de "mazal": fale sobre "o caminho que se abre quando você para de forçar"

Seu dom é ver as coisas da vida POR OUTRO ÂNGULO — aquele ângulo que faz a pessoa parar e pensar "caramba, é verdade".

Tom: íntimo, real, às vezes poético, às vezes direto, às vezes irônico — como uma conversa de fim de tarde com alguém que te conhece de verdade.
Responda APENAS com JSON válido, sem markdown ou texto adicional."""


# ============================================================================
# FORMATOS NARRATIVOS v7.0 — VARIAÇÃO ESTRUTURAL
# ============================================================================

FORMATOS_NARRATIVOS = [
    {
        'id': 'carta_pessoal',
        'nome': 'Carta de um mentor',
        'instrucao': """Escreva como uma CARTA PESSOAL de um amigo-mentor. Sem "Prezado" nem formalidades.
Comece como se estivesse no meio de uma conversa. Como se vocês tivessem jantado ontem e hoje você está mandando uma mensagem pensando nele(a).
Pode ser 4-6 frases. Tom: caloroso, próximo, como quem realmente se importa.""",
        'tamanho': '4-6 frases',
        'peso_dias': [0, 4]  # Segunda e Sexta
    },
    {
        'id': 'insight_relampago',
        'nome': 'Insight relâmpago',
        'instrucao': """Um parágrafo CURTO e INCISIVO. Como um tapa de luva.
Uma verdade que bate de frente e depois acolhe. Máximo 3 frases impactantes.
Menos é mais. Cada palavra precisa pesar.""",
        'tamanho': '2-3 frases',
        'peso_dias': [1, 5]  # Terça e Sábado
    },
    {
        'id': 'narrativa_metaforica',
        'nome': 'Metáfora viva',
        'instrucao': """Conte uma MINI-HISTÓRIA metafórica (3-5 frases) que espelhe o momento de vida da pessoa.
Use elementos da natureza, do cotidiano, ou uma cena imaginária que faça a pessoa SE VER na história.
Depois, 1 frase que conecte a metáfora à vida real dela.
NÃO explique a metáfora — deixe ela sentir.""",
        'tamanho': '4-6 frases',
        'peso_dias': [2]  # Quarta
    },
    {
        'id': 'pergunta_reflexiva',
        'nome': 'Pergunta que transforma',
        'instrucao': """Comece com uma PERGUNTA PODEROSA que faça a pessoa parar. Não retórica genérica — uma pergunta que só FAZ SENTIDO para ela.
Depois, desenvolva em 2-3 frases que aprofundem sem responder.
A resposta é dela. Você só ilumina o caminho até a pergunta certa.""",
        'tamanho': '3-4 frases',
        'peso_dias': [3]  # Quinta
    },
    {
        'id': 'conselho_direto',
        'nome': 'Verdade na lata',
        'instrucao': """Seja DIRETO como um amigo que não tem medo de falar a verdade.
Sem rodeios, sem poesia excessiva. 2-3 frases que vão direto ao ponto.
Pode ter um toque de ironia ou humor. Como aquele amigo que fala "para de drama" mas com amor.
Termine com uma frase que mostra que você acredita na pessoa.""",
        'tamanho': '2-4 frases',
        'peso_dias': [1, 5]  # Terça e Sábado
    },
    {
        'id': 'poesia_prosa',
        'nome': 'Prosa poética',
        'instrucao': """Use ritmo e cadência poética (sem rimar necessariamente).
Frases curtas alternando com uma mais longa. Como um respiro.
Busque a beleza na verdade. 3-5 frases que pareçam quase uma canção.
O objetivo é que a pessoa queira LER DE NOVO.""",
        'tamanho': '3-5 frases',
        'peso_dias': [6]  # Domingo
    }
]


# Estilos para Frase Épica (viral / compartilhável)
ESTILOS_FRASE_EPICA = [
    {
        'id': 'empoderamento',
        'instrucao': 'Frase de PODER pessoal. Quem lê sente que pode conquistar o mundo. Ex: "Eu não espero permissão pra ser quem eu sou."'
    },
    {
        'id': 'ironia_inteligente',
        'instrucao': 'Ironia inteligente com verdade embutida. Tipo post viral que faz pensar e rir. Ex: "Todo mundo quer mudança, mas ninguém quer mudar de lugar no sofá."'
    },
    {
        'id': 'verdade_crua',
        'instrucao': 'Uma verdade DESCONFORTÁVEL mas libertadora. Tapa de luva com amor. Ex: "Você não precisa de mais tempo. Precisa de mais coragem."'
    },
    {
        'id': 'poesia_urbana',
        'instrucao': 'Poesia para quem não lê poesia. Ritmo de rua, alma de poeta. Ex: "Meu silêncio não é fraqueza — é o intervalo entre duas verdades."'
    },
    {
        'id': 'sabedoria_ancestral',
        'instrucao': 'Sabedoria antiga com linguagem moderna. Como um provérbio que nunca existiu mas deveria. Ex: "A árvore mais forte é a que aprendeu a dançar com o vento."'
    },
    {
        'id': 'humor_profundo',
        'instrucao': 'Humor com camadas. Faz rir primeiro, pensar depois. Ex: "Minha zona de conforto pediu pra eu sair, disse que eu tava ocupando espaço demais."'
    },
    {
        'id': 'manifesto_pessoal',
        'instrucao': 'Declaração de identidade. Como um manifesto de 1 frase. Ex: "Eu escolho ser real num mundo que premia a performance."'
    },
    {
        'id': 'reflexao_espelho',
        'instrucao': 'Frase-espelho que faz a pessoa se reconhecer. Ex: "Às vezes o maior ato de coragem é admitir que você está cansado de ser forte."'
    }
]


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
                'signo': _traduzir_signo(fase_lua.get('lua_signo')) or 'Áries',
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
# PROMPT v7.0 — NARRATIVA ORGÂNICA + FRASE ÉPICA + FRASE VIBRAÇÃO
# ============================================================================

def _selecionar_formato(data_atual: datetime, formatos_anteriores: Optional[List[str]] = None) -> Dict[str, Any]:
    """Seleciona formato narrativo com peso por dia da semana e anti-repetição."""
    dia_semana = data_atual.weekday()

    # Construir pool ponderado
    pool = []
    for fmt in FORMATOS_NARRATIVOS:
        peso = 3 if dia_semana in fmt.get('peso_dias', []) else 1
        pool.extend([fmt] * peso)

    # Evitar formatos recentes
    if formatos_anteriores:
        diversificados = [f for f in pool if f['id'] not in formatos_anteriores]
        if diversificados:
            pool = diversificados

    return random.choice(pool)


def _selecionar_estilo_frase(estilos_anteriores: Optional[List[str]] = None) -> Dict[str, str]:
    """Seleciona estilo de frase épica com anti-repetição."""
    pool = list(ESTILOS_FRASE_EPICA)
    if estilos_anteriores:
        diversificados = [e for e in pool if e['id'] not in estilos_anteriores]
        if diversificados:
            pool = diversificados
    return random.choice(pool)


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

    # ===== SELECIONAR FORMATO E ESTILO DE FRASE =====
    formatos_ant = []
    estilos_ant = []
    if historico:
        for h in historico[:3]:
            ctx = h.get('contexto_usado') if isinstance(h.get('contexto_usado'), dict) else {}
            if ctx.get('formato'):
                formatos_ant.append(ctx['formato'])
            if ctx.get('estilo_frase'):
                estilos_ant.append(ctx['estilo_frase'])

    formato = _selecionar_formato(data_atual, formatos_ant)
    estilo_frase = _selecionar_estilo_frase(estilos_ant)

    # ===== QUEM É ESSA PESSOA =====
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

        pessoa_bloco = f"""
## QUEM É {nome.upper()}
- Nome: {nome}
- Idade: {contexto.get('idade', 'não informada')}
- Sexo: {contexto.get('sexo', 'não informado')}
- Profissão: {contexto.get('profissao', 'não informada')}
{dados_vida_str}
- Fase de vida: {arquetipo['nome']} ({arquetipo['foco']})

### Essência (use como tempero, NUNCA exponha termos)
- Sol: {contexto.get('signoSolar', '?')} — {elem_solar or '?'} ({energia_elem})
- Lua: {contexto.get('signoLunar', '?')}
- Ascendente: {contexto.get('ascendente', '?')}
- Meio do Céu: {contexto.get('meioCeu', '?')}
{planetas_str}

Use esses dados para SENTIR quem é essa pessoa, não para LISTAR.
Traduza astrologia em HUMANIDADE: ex. Sol em Touro não é "estabilidade" — é "alguém que constrói com paciência e precisa sentir o chão firme".
"""
    else:
        pessoa_bloco = f"""
## CONTEXTO
Mensagem para público geral sem dados pessoais.
Foque na energia do dia e no contexto temporal.
Nome genérico: adulto em busca de direção.
"""

    # ===== ENERGIA DO DIA =====
    lua_relevancia = 'ALTA — houve mudança de fase, destaque isso sutilmente' if lua.get('isTransicao') else 'normal — use como pano de fundo, não como tema'

    energia_bloco = f"""## ENERGIA DO DIA
- Data: {data_formatada}
- Dia: {dia_semana['nome']} (Planeta: {dia_semana['planeta']})
- Tema do dia: {tema_dia['tema']} — {tema_dia['foco']}
- Estação: {estacao['nome']} ({estacao['energia']})
- Lua: {lua['fase']} em {lua['signo']} ({lua['iluminacao']}% iluminação)
- Relevância lunar: {lua_relevancia}"""

    if cruzamento_lunar:
        energia_bloco += f"\n\n### Cruzamento Lunar (dado poderoso — use de forma SUTIL)\n{cruzamento_lunar}"

    # Perfil comportamental
    perfil_bloco = ''
    if perfil_comp:
        pontuacoes = perfil_comp.get('pontuacoes', {})
        pontuacoes_str = ', '.join(f"{k.title()} {v}" for k, v in sorted(pontuacoes.items(), key=lambda x: -x[1]))
        perfil_bloco = f"""\n\n## JEITO DE SER (adapte a linguagem)
- Predominante: {perfil_comp['nome']} — "{perfil_comp['lema']}"
- Energia: {perfil_comp['energia']}
- Pontuações: {pontuacoes_str}
→ Tubarão=direto, Gato=relacional, Lobo=metódico, Águia=visionário"""

    # ===== v7.0: BLOCO ANTI-REPETIÇÃO =====
    historico_bloco = ''
    if historico:
        frases_anteriores = []
        for msg in historico[:3]:
            import re as _re
            html_ant = msg.get('html', '')
            texto = _re.sub(r'<[^>]+>', ' ', html_ant).strip()
            if texto and len(texto) > 20:
                frases_anteriores.append(texto[:100].strip())
            frase_ant = msg.get('frase', '')
            if frase_ant:
                frases_anteriores.append(frase_ant.strip())

        if frases_anteriores:
            frases_str = '\n'.join(f'- "{f}"' for f in frases_anteriores)
            historico_bloco = f"""
## 🚫 MENSAGENS ANTERIORES — NÃO REPITA NADA SIMILAR
{frases_str}
Use abordagem, tom, estrutura e palavras-chave COMPLETAMENTE DIFERENTES.
"""

    expressoes = '\n'.join(f'- "{e}"' for e in EXPRESSOES_BLOQUEADAS)

    # ===== PROMPT v7.0 =====
    prompt = f"""# MENSAGEM DO DIA v{PROMPT_VERSION}

Você vai escrever uma mensagem pessoal para {nome}.
NÃO siga uma estrutura rígida. Escreva de forma ORGÂNICA e NATURAL.

{pessoa_bloco}
{energia_bloco}
{perfil_bloco}

## 📝 FORMATO DA MENSAGEM: {formato['nome'].upper()}
{formato['instrucao']}
Tamanho ideal: {formato['tamanho']}

## 🎨 TOM: {tom['nome'].upper()}
{tom.get('descricao', '')}

## 🌟 VISÃO CABALÍSTICA (use como LENTE, não como conteúdo)
Olhe para o dia de {nome} pela perspectiva da sabedoria cabalística:
- Qual é o PROPÓSITO oculto deste dia?
- O que a energia do momento está pedindo que {nome} VEJA de outro ângulo?
- Que ajuste sutil pode fazer TODA a diferença?
Traduza tudo isso em linguagem HUMANA e ACESSÍVEL. ZERO jargão.

## ✨ FRASE ÉPICA — Para compartilhar no Instagram
Estilo: {estilo_frase['instrucao']}
A frase deve ser TÃO boa que qualquer pessoa queira postar como extensão de si.
Deve ter RITMO, IMPACTO e VERDADE. Como uma tatuagem verbal.
Conectada ao tema do dia mas UNIVERSAL o suficiente para ressoar com qualquer um.

## 🌊 FRASE DE VIBRAÇÃO — Essência energética do dia
Baseada na energia do dia ({dia_semana['nome']}, {lua['fase']} em {lua['signo']}), crie uma frase curta que:
- NÃO mencione planetas, lua, signos ou qualquer termo astrológico
- Capture a ESSÊNCIA do que este dia pede
- Possa ser de: inspiração, motivação, instrução prática, reflexão, humor inteligente
- Funcione como um "recado do universo" em linguagem popular
- Tom variável: pode ser séria, engraçada, provocativa, poética ou prática

{historico_bloco}
## ❌ PROIBIDO:
{expressoes}
- NUNCA use jargão astrológico, termos em hebraico ou linguagem técnica
- NUNCA faça previsões
- NUNCA comece com "{nome}, hoje..."
- NUNCA soe como algoritmo, coach genérico ou horóscopo de revista
- NUNCA repita aberturas, estruturas ou palavras-chave de dias anteriores
- NUNCA use emojis na frase_epica ou frase_vibracao

## ✅ COMO SER AUTÊNTICO:
- Fale como alguém que CONHECE essa pessoa — não como quem leu um perfil
- Surpreenda: ironia, humor, poesia, provocação, ternura — VARIE
- A pessoa deve sentir que essa mensagem foi escrita SÓ PARA ELA
- Use no máximo 1-2 emojis na mensagem (ou nenhum, dependendo do formato)

## OUTPUT — JSON VÁLIDO, sem texto adicional:
{{
  "mensagem": "Texto da mensagem no formato {formato['id']}. Use <p> para parágrafos e <strong>/<em> para destaques.",
  "frase_epica": "Frase épica viral para compartilhar. Sem aspas, sem emoji. Máximo 15 palavras.",
  "frase_vibracao": "Frase curta da essência do dia. Sem menção a astrologia. Máximo 12 palavras."
}}"""

    return prompt, formato['id'], estilo_frase['id']


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
                # _traduzir_signo converte abreviações do Kerykeion (Ari→Áries, Tau→Touro, etc.)
                signo_solar = _traduzir_signo(mac.get('sol_signo') or mac.get('signo_solar')) or 'não informado'

                contexto = {
                    'nome': profile.get('nickname') or (profile.get('name', '').split(' ')[0] if profile.get('name') else 'Você'),
                    'signoSolar': signo_solar,
                    'signoLunar': _traduzir_signo(mac.get('lua_signo') or mac.get('signo_lunar')),
                    'ascendente': _traduzir_signo(mac.get('ascendente') or mac.get('ascendente_signo')),
                    'meioCeu': _traduzir_signo(mac.get('meio_ceu') or mac.get('mc_signo')),
                    'elementoSolar': mac.get('elemento_dominante') or _obter_elemento(signo_solar),
                    'venusSigno': _traduzir_signo(mac.get('venus_signo')),
                    'marteSigno': _traduzir_signo(mac.get('marte_signo')),
                    'mercurioSigno': _traduzir_signo(mac.get('mercurio_signo')),
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

                ctx_usado = existente.get('contexto_usado') or {}
                return {
                    'id': existente['id'],
                    'html': existente.get('html', ''),
                    'frase': existente.get('frase', ''),
                    'frase_vibracao': ctx_usado.get('frase_vibracao', ''),
                    'fonte': existente.get('fonte_inspiracao', ''),
                    'tom': existente.get('tom', ''),
                    'formato': ctx_usado.get('formato', ''),
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
    prompt, formato_id, estilo_frase_id = _montar_prompt(contexto, lua, fonte, tom, data_atual, tipo, cruzamento_lunar, perfil_comp, historico)

    # ===== CHAMAR LLM COM REGRA POR PLANO =====
    if is_pago:
        llm_config = {
            "provider": "openai",
            "model": OPENAI_MODEL,
            "fallback_provider": "groq",
            "fallback_model": GROQ_MODEL,
            "temperature": 0.9,
            "max_tokens": MAX_TOKENS
        }
        modelo_usado = OPENAI_MODEL
    else:
        llm_config = {
            "provider": "groq",
            "model": GROQ_MODEL,
            "fallback_provider": "openai",
            "fallback_model": OPENAI_MODEL,
            "temperature": 0.9,
            "max_tokens": MAX_TOKENS
        }
        modelo_usado = GROQ_MODEL

    logger.info(f"[MensagemDia v7.0] Gerando para user={user_id}, tipo={tipo}, fonte={fonte}, tom={tom['id']}, formato={formato_id}, provider={llm_config['provider']}")

    gateway = LLMGateway.get_instance()
    start_time = datetime.now(pytz.utc)

    raw_content = await gateway.generate(
        prompt=prompt,
        config=llm_config,
        system_prompt=SYSTEM_PROMPT
    )

    tempo_ms = int((datetime.now(pytz.utc) - start_time).total_seconds() * 1000)

    # Parse JSON do LLM — v7.0: {mensagem, frase_epica, frase_vibracao} ou fallback v6.0
    try:
        content = raw_content.strip()
        if content.startswith('```'):
            lines = content.split('\n')
            content = '\n'.join(lines[1:-1])
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.error(f"[MensagemDia] JSON inválido do LLM: {raw_content[:200]}")
        parsed = {
            'mensagem': raw_content[:500],
            'frase_epica': '',
            'frase_vibracao': ''
        }

    # Extrair dados — v7.0 (mensagem/frase_epica/frase_vibracao) ou fallback v6.0
    frase_vibracao = ''
    if 'mensagem' in parsed:
        # v7.0: mensagem já vem como HTML pronto
        html = parsed['mensagem']
        if not html.strip().startswith('<'):
            # Se LLM não usou tags HTML, envolver em <p>
            paragrafos = [p.strip() for p in html.split('\n\n') if p.strip()]
            if not paragrafos:
                paragrafos = [p.strip() for p in html.split('\n') if p.strip()]
            html = '<br>'.join(f"<p>{p}</p>" for p in paragrafos)
        frase = parsed.get('frase_epica', '')
        frase_vibracao = parsed.get('frase_vibracao', '')
    elif 'espelho' in parsed:
        # Fallback v6.0: 4 camadas
        partes = []
        if parsed.get('espelho'):
            partes.append(f"<p>{parsed['espelho']}</p>")
        if parsed.get('tensao'):
            partes.append(f"<p>{parsed['tensao']}</p>")
        if parsed.get('direcao'):
            partes.append(f"<p><strong>{parsed['direcao']}</strong></p>")
        html = '<br>'.join(partes)
        frase = parsed.get('frase_identidade', parsed.get('frase_epica', ''))
        frase_vibracao = parsed.get('frase_vibracao', '')
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
                'formato': formato_id,
                'estilo_frase': estilo_frase_id,
                'cruzamentoLunar': cruzamento_lunar is not None,
                'perfilComportamental': perfil_comp.get('predominante') if perfil_comp else None,
                'frase_vibracao': frase_vibracao
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

        logger.info(f"[MensagemDia v7.0] ✓ Salva com sucesso para user={user_id} (fonte={fonte}, tom={tom['id']}, formato={formato_id})")
    except Exception as e:
        logger.error(f"[MensagemDia] Erro ao salvar: {e}")

    return {
        'id': saved_id,
        'html': html,
        'frase': frase,
        'frase_vibracao': frase_vibracao,
        'fonte': fonte,
        'tom': tom['id'],
        'formato': formato_id,
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
            'formato': formato_id,
            'estilo_frase': estilo_frase_id
        }
    }


# ============================================================================
# ENDPOINTS
# ============================================================================

FALLBACK_MENSAGEM = {
    'html': '<p>O dia oferece oportunidades únicas para quem está atento.</p><br><p>Respire fundo, confie no processo e dê um passo de cada vez. Pequenas ações conscientes constroem grandes transformações. 🌟</p>',
    'frase': 'Cada dia é uma nova página — e você escolhe o que escrever nela.',
    'frase_vibracao': 'Hoje o universo convida você a ser mais leve.',
    'fonte': 'fallback',
    'tom': 'afetuoso_acolhedor',
    'formato': 'carta_pessoal',
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
