"""
Router: Daily Message (Mensagem do Dia)

Gera mensagens inspiracionais diárias PROFUNDAMENTE personalizadas usando IA.
Prompt v4.0 — Contexto astrológico rico, dados pessoais, cruzamentos,
numerologia e distribuição inteligente de fontes.

Endpoints:
- POST /daily-message/generate — Gera ou retorna mensagem do dia
- POST /daily-message/regenerate — Regenera a mensagem (1x/dia)
- POST /daily-message/rate — Registra rating da mensagem
"""

import json
import random
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
# CONSTANTES v4.0
# ============================================================================

PROMPT_VERSION = "4.0"
MAX_TOKENS = 700
GROQ_MODEL = "llama-3.3-70b-versatile"
OPENAI_MODEL = "gpt-4.1-mini"

EXPRESSOES_BLOQUEADAS = [
    'meu bem', 'querida', 'querido', 'meu amor',
    'minha flor', 'benzinho', 'amor da minha vida',
    'meu anjo', 'meu dengo', 'alma querida',
    'meu caro', 'minha cara'
]

# Fontes expandidas v4.0
FONTES = [
    'dia_semana', 'fase_lua', 'ascendente', 'meio_ceu',
    'profissao_contexto', 'reflexao_existencial', 'estacao_clima',
    'micro_momento', 'metafora_criativa', 'aniversario', 'feriado',
    'elemento_pessoal', 'cruzamento_lunar', 'numerologia_dia',
    'planeta_regente_dia', 'casa_lua_natal', 'roda_da_vida',
    'venus_e_afetos', 'marte_e_acao'
]

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

# Numerologia — significados dos números
NUMEROLOGIA_SIGNIFICADOS = {
    1: {'tema': 'Início', 'energia': 'liderança, independência, novo começo, plantar sementes'},
    2: {'tema': 'Parceria', 'energia': 'cooperação, diplomacia, equilíbrio, escutar o outro'},
    3: {'tema': 'Expressão', 'energia': 'criatividade, comunicação, alegria, socializar'},
    4: {'tema': 'Estrutura', 'energia': 'disciplina, organização, bases sólidas, paciência'},
    5: {'tema': 'Liberdade', 'energia': 'mudança, aventura, adaptabilidade, sair da zona de conforto'},
    6: {'tema': 'Responsabilidade', 'energia': 'família, harmonia, cuidado, lar, amor'},
    7: {'tema': 'Introspecção', 'energia': 'espiritualidade, análise, descanso mental, sabedoria'},
    8: {'tema': 'Poder', 'energia': 'abundância, conquistas materiais, autoridade, ambição'},
    9: {'tema': 'Conclusão', 'energia': 'encerramento de ciclos, compaixão, desapego, humanidade'},
}

SYSTEM_PROMPT = """Você é um mentor de autoconhecimento e astrologia que gera mensagens diárias personalizadas para o app Vibra EU.
Você conhece profundamente a pessoa e fala diretamente para ela, como um guia sábio e próximo.
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
# FUNÇÕES AUXILIARES v4.0
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


def _calcular_numerologia_dia(data: datetime) -> Dict[str, Any]:
    """Calcula o número pessoal do dia pela soma reduzida da data."""
    date_str = data.strftime("%Y%m%d")
    soma = sum(int(d) for d in date_str)
    while soma > 9:
        soma = sum(int(d) for d in str(soma))
    info = NUMEROLOGIA_SIGNIFICADOS.get(soma, {'tema': 'Fluxo', 'energia': 'estar presente'})
    return {
        'numero': soma,
        'tema': info['tema'],
        'energia': info['energia']
    }


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


def _obter_resumo_roda_vida(sb, user_id: str) -> Optional[Dict[str, Any]]:
    """Busca a Roda da Vida mais recente e retorna as 2 áreas mais fortes e 2 mais fracas."""
    try:
        areas_campos = [
            'saude_fisica', 'saude_mental', 'financas', 'carreira',
            'relacionamentos', 'familia', 'espiritualidade', 'lazer',
            'crescimento_pessoal', 'contribuicao', 'ambiente', 'proposito'
        ]
        resp = sb.client.table('roda_vida') \
            .select(', '.join(areas_campos)) \
            .eq('user_id', user_id) \
            .order('created_at', desc=True) \
            .limit(1) \
            .execute()

        if not resp.data:
            return None

        roda = resp.data[0]
        notas = {}
        for campo in areas_campos:
            val = roda.get(campo)
            if val is not None:
                label = campo.replace('_', ' ').title()
                notas[label] = val

        if len(notas) < 4:
            return None

        ordenado = sorted(notas.items(), key=lambda x: x[1])
        mais_fracas = ordenado[:2]
        mais_fortes = ordenado[-2:]

        return {
            'mais_fortes': [{'area': a, 'nota': n} for a, n in mais_fortes],
            'mais_fracas': [{'area': a, 'nota': n} for a, n in mais_fracas],
        }
    except Exception as e:
        logger.warning(f"[MensagemDia] Erro ao buscar Roda da Vida: {e}")
        return None


# ============================================================================
# SELEÇÃO DE FONTE E TOM
# ============================================================================

def _selecionar_fonte(pesos_data: Optional[List], lua: Dict, data_nascimento: Optional[str], data_atual: datetime) -> str:
    if _is_aniversario(data_nascimento, data_atual):
        return 'aniversario'

    if not pesos_data:
        return random.choice(FONTES)

    pesos_calculados = []
    for p in pesos_data:
        peso_final = p.get('peso_base', 1)
        condicao_boost = p.get('condicao_boost', {})
        if condicao_boost:
            if condicao_boost.get('inicio_fase') and lua.get('isTransicao') and p.get('fonte') == 'fase_lua':
                peso_final *= condicao_boost['inicio_fase']
        pesos_calculados.append({'fonte': p['fonte'], 'peso': peso_final})

    total_peso = sum(p['peso'] for p in pesos_calculados)
    r = random.random() * total_peso
    for p in pesos_calculados:
        r -= p['peso']
        if r <= 0:
            return p['fonte']

    return 'reflexao_existencial'


def _selecionar_tom() -> Dict[str, str]:
    tom = random.choice(TONS)
    return {'id': tom['id'], 'nome': tom['nome']}


# ============================================================================
# PROMPT v4.0 — PROFUNDAMENTE PERSONALIZADO
# ============================================================================

def _montar_prompt(
    contexto: Dict[str, Any],
    lua: Dict[str, Any],
    fonte: str,
    tom: Dict[str, str],
    data_atual: datetime,
    tipo: str,  # 'personalizada' | 'generica'
    numerologia: Dict[str, Any],
    cruzamento_lunar: Optional[str],
    roda_vida: Optional[Dict[str, Any]]
) -> str:
    dia_semana = _get_dia_semana(data_atual)

    meses = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
             'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
    dias = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira',
            'sexta-feira', 'sábado', 'domingo']
    data_formatada = f"{dias[data_atual.weekday()]}, {data_atual.day} de {meses[data_atual.month - 1]} de {data_atual.year}"

    nome = contexto.get('nome', 'Você')

    # ===== BLOCO DE CONTEXTO PESSOAL =====
    if tipo == 'personalizada':
        elem_solar = contexto.get('elementoSolar') or _obter_elemento(contexto.get('signoSolar'))
        energia_elem = ENERGIA_ELEMENTOS.get(elem_solar, '') if elem_solar else ''

        # Dados pessoais de vida
        dados_vida = []
        if contexto.get('estadoCivil'):
            dados_vida.append(f"- Estado civil: {contexto['estadoCivil']}")
        if contexto.get('temFilhos'):
            val = contexto['temFilhos']
            dados_vida.append(f"- Tem filhos: {'Sim' if val in ['sim', 'Sim', True, 'true'] else 'Não'}")
        dados_vida_str = '\n'.join(dados_vida) if dados_vida else ''

        # Planetas pessoais
        planetas = []
        if contexto.get('venusSigno') and contexto['venusSigno'] != 'não informado':
            planetas.append(f"- Vênus (amor/valores): {contexto['venusSigno']}")
        if contexto.get('marteSigno') and contexto['marteSigno'] != 'não informado':
            planetas.append(f"- Marte (ação/energia): {contexto['marteSigno']}")
        if contexto.get('mercurioSigno') and contexto['mercurioSigno'] != 'não informado':
            planetas.append(f"- Mercúrio (mente/comunicação): {contexto['mercurioSigno']}")
        planetas_str = '\n'.join(planetas) if planetas else ''

        contexto_bloco = f"""
### Contexto Pessoal de {nome}
- Nome: {nome}
- Idade: {contexto.get('idade', 'não informada')}
- Sexo: {contexto.get('sexo', 'não informado')}
- Profissão: {contexto.get('profissao', 'não informada')}
{dados_vida_str}

### Mapa Astral (MAC)
- ☀️ Sol: {contexto.get('signoSolar', 'não informado')} — Elemento {elem_solar or 'não informado'} ({energia_elem})
- 🌙 Lua: {contexto.get('signoLunar', 'não informado')}
- ⬆️ Ascendente: {contexto.get('ascendente', 'não informado')}
- 🏔️ Meio do Céu: {contexto.get('meioCeu', 'não informado')}
{planetas_str}
"""
    else:
        contexto_bloco = """
### Contexto Genérico
Mensagem para público geral sem dados astrológicos pessoais.
Foque na energia do dia, da lua e no contexto temporal.
"""

    # ===== BLOCO DE LUA =====
    lua_bloco = f"""## 🌙 LUA DO DIA
- Fase: {lua['fase']} ({lua['faseSimplificada']})
- Signo da Lua hoje: {lua['signo']}
- Iluminação: {lua['iluminacao']}%
- É transição de fase: {'SIM ✅ — DESTAQUE ESPECIAL! A lua mudou de fase, isso é significativo!' if lua.get('isTransicao') else 'Não'}
"""

    # ===== CRUZAMENTO LUNAR =====
    cruzamento_bloco = ''
    if cruzamento_lunar:
        cruzamento_bloco = f"""
## 🔮 CRUZAMENTO LUNAR (Lua do dia × Lua natal)
{cruzamento_lunar}
→ USE este cruzamento para personalizar a mensagem. É um dado poderoso.
"""

    # ===== NUMEROLOGIA =====
    numero_bloco = f"""## 🔢 NUMEROLOGIA DO DIA: {numerologia['numero']}
- Tema: {numerologia['tema']}
- Energia: {numerologia['energia']}
"""

    # ===== RODA DA VIDA =====
    roda_bloco = ''
    if roda_vida:
        fortes = ', '.join(f"{a['area']} ({a['nota']})" for a in roda_vida['mais_fortes'])
        fracas = ', '.join(f"{a['area']} ({a['nota']})" for a in roda_vida['mais_fracas'])
        roda_bloco = f"""
## 🎯 RODA DA VIDA (autoavaliação recente)
- Áreas mais fortes: {fortes}
- Áreas pedindo atenção: {fracas}
→ Quando a fonte for 'roda_da_vida', use isso como gancho principal.
"""

    # ===== INSTRUÇÕES POR FONTE =====
    instrucoes_fonte = {
        'dia_semana': f"Foque na energia de {dia_semana['nome']} regida por {dia_semana['planeta']}: {dia_semana['energia']}.",
        'fase_lua': f"A lua está {lua['fase']} em {lua['signo']}. Explore o significado dessa fase e como ela influencia o dia.",
        'ascendente': f"O ascendente de {nome} revela como ela se apresenta ao mundo. Use isso.",
        'meio_ceu': f"O Meio do Céu revela a vocação e propósito profissional de {nome}. Conecte com o dia.",
        'profissao_contexto': f"Considere a profissão de {nome} ({contexto.get('profissao', 'não informada')}) como contexto.",
        'reflexao_existencial': "Faça uma reflexão profunda sobre a vida, o momento, os ciclos.",
        'estacao_clima': f"Estamos em fevereiro no hemisfério sul — verão, calor, energia expansiva.",
        'micro_momento': "Traga um micro-momento do cotidiano como metáfora (café da manhã, espelho, primeiro passo).",
        'metafora_criativa': "Use uma metáfora criativa e original como fio condutor da mensagem.",
        'aniversario': f"Hoje é aniversário de {nome}! Celebre de forma especial e significativa.",
        'feriado': "Se hoje for feriado ou data especial, conecte com a mensagem.",
        'elemento_pessoal': f"Explore o elemento {contexto.get('elementoSolar', '')} de {nome} e como ele interage com o dia.",
        'cruzamento_lunar': "Use o cruzamento entre a lua do dia e a lua natal como base principal.",
        'numerologia_dia': f"O número do dia é {numerologia['numero']} — tema '{numerologia['tema']}'. Use como fio condutor.",
        'planeta_regente_dia': f"{dia_semana['nome']} é regida por {dia_semana['planeta']}. Aprofunde a relação com o mapa da pessoa.",
        'casa_lua_natal': "Explore a casa onde a lua natal está posicionada e o que isso significa no cotidiano.",
        'roda_da_vida': "Use as áreas da Roda da Vida da pessoa como gancho principal da mensagem.",
        'venus_e_afetos': f"Explore Vênus ({contexto.get('venusSigno', 'não informado')}) — amor próprio, valores, relações.",
        'marte_e_acao': f"Explore Marte ({contexto.get('marteSigno', 'não informado')}) — ação, coragem, energia vital.",
    }

    instrucao_fonte = instrucoes_fonte.get(fonte, 'Use abordagem criativa e variada.')

    expressoes = '\n'.join(f'- "{e}"' for e in EXPRESSOES_BLOQUEADAS)

    # ===== PROMPT FINAL =====
    prompt = f"""# GERADOR DE MENSAGEM INSPIRACIONAL v{PROMPT_VERSION}

## MODO: {tipo.upper()}
{contexto_bloco}

## DATA E CONTEXTO TEMPORAL
- Data: {data_formatada}
- Dia da Semana: {dia_semana['nome']} (Planeta regente: {dia_semana['planeta']})
- Energia do dia: {dia_semana['energia']}

{lua_bloco}
{cruzamento_bloco}
{numero_bloco}
{roda_bloco}

## 🎯 FONTE DE INSPIRAÇÃO: {fonte.upper().replace('_', ' ')}
{instrucao_fonte}

## 🎭 TOM: {tom['nome'].upper()}
Ajuste a linguagem e abordagem de acordo com este tom.

## ⚡ REGRAS OBRIGATÓRIAS v4.0

### ❌ NUNCA faça:
{expressoes}
- NUNCA comece a mensagem com "Você, hoje, ..." — VARIE a abertura!
- NUNCA comece com "{nome}, hoje..." em TODAS as mensagens — varie!
- NUNCA use estrutura repetitiva

### ✅ COMO ESCREVER:
- Fale diretamente para {nome}, como alguém que a conhece profundamente
- Varie SEMPRE a abertura. Exemplos de aberturas variadas:
  • Comece com uma pergunta reflexiva
  • Comece com a energia do dia/lua
  • Comece com uma metáfora
  • Comece com um insight astrológico
  • Comece com o nome + algo inesperado
  • Comece pela numerologia ou pela fase da lua
- A pessoa deve sentir que a mensagem foi escrita PARA ELA
- Ajude-a a se PREPARAR para o dia, com insights práticos e emocionais
- Integre os elementos astrológicos de forma natural (não como lista de dados)
- Seja um guia sábio que conhece os astros E conhece a pessoa

### 🔮 OBRIGATÓRIO — INTEGRE PELO MENOS 2 DESTES:
1. A fase/signo da lua do dia
2. Um elemento do mapa astral da pessoa (Sol, Lua, ASC, planetas)
3. A energia do dia da semana / planeta regente
4. A numerologia do dia
5. Um aspecto pessoal (profissão, estado civil, filhos, idade)

## OUTPUT
Responda APENAS com JSON válido, sem texto adicional:
{{
  "html": "<p>...</p><br><p>...</p>",
  "frase": "..."
}}

Regras do HTML:
- Use <p>, <br>, <strong>, <em>
- 2-3 parágrafos (6-10 linhas total) — pode ser mais rico que antes
- 1-2 emojis estratégicos e contextuais (lua, estrela, fogo, etc)
- O último parágrafo deve ter uma orientação prática ou reflexão de encerramento

Regras da Frase (exibida como destaque visual na tela):
- Frase curta e impactante (1-2 linhas)
- Sem emojis na frase
- Pode usar <strong> ou <em>
- Deve funcionar como um "mantra do dia" ou insight memorável"""

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

    # ===== DADOS ENRIQUECIDOS v4.0 =====
    numerologia = _calcular_numerologia_dia(data_atual)
    cruzamento_lunar = _cruzamento_lua_dia_natal(
        lua.get('signo', ''),
        contexto.get('signoLunar')
    ) if tipo == 'personalizada' else None

    roda_vida = None
    if tipo == 'personalizada' and user_id:
        roda_vida = _obter_resumo_roda_vida(sb, user_id)

    # Buscar pesos do banco
    pesos_data = None
    try:
        pesos_resp = sb.client.table('mensagem_pesos') \
            .select('*') \
            .eq('ativo', True) \
            .execute()
        pesos_data = pesos_resp.data
    except Exception as e:
        logger.warning(f"[MensagemDia] Sem pesos no banco: {e}")

    fonte = _selecionar_fonte(pesos_data, lua, contexto.get('dataNascimento'), data_atual)
    tom = _selecionar_tom()
    prompt = _montar_prompt(contexto, lua, fonte, tom, data_atual, tipo, numerologia, cruzamento_lunar, roda_vida)

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

    logger.info(f"[MensagemDia v4.0] Gerando para user={user_id}, tipo={tipo}, fonte={fonte}, tom={tom['id']}, provider={llm_config['provider']}")

    gateway = LLMGateway.get_instance()
    start_time = datetime.now(pytz.utc)

    raw_content = await gateway.generate(
        prompt=prompt,
        config=llm_config,
        system_prompt=SYSTEM_PROMPT
    )

    tempo_ms = int((datetime.now(pytz.utc) - start_time).total_seconds() * 1000)

    # Parse JSON do LLM
    try:
        content = raw_content.strip()
        if content.startswith('```'):
            lines = content.split('\n')
            content = '\n'.join(lines[1:-1])
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.error(f"[MensagemDia] JSON inválido do LLM: {raw_content[:200]}")
        parsed = {
            'html': f'<p>{raw_content[:500]}</p>',
            'frase': raw_content[:200] if len(raw_content) <= 200 else raw_content[:200] + '...'
        }

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
                'numerologia': numerologia['numero'],
                'fonte': fonte,
                'tom': tom['id'],
                'cruzamentoLunar': cruzamento_lunar is not None,
                'rodaVida': roda_vida is not None
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

        logger.info(f"[MensagemDia v4.0] ✓ Salva com sucesso para user={user_id} (fonte={fonte}, tom={tom['id']})")
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
            'numerologia': numerologia['numero']
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
