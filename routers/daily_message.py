"""
Router: Daily Message (Mensagem do Dia)

Gera mensagens inspiracionais diárias personalizadas usando IA.
Migrado da Edge Function generate-daily-message para API Python nativa.

Usa o astro_engine (Kerykeion) para dados astronômicos reais de lua e planetas,
em vez de cálculos manuais aproximados.

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
# CONSTANTES (migradas da Edge Function)
# ============================================================================

PROMPT_VERSION = "3.0"
MAX_TOKENS = 500
GROQ_MODEL = "llama-3.3-70b-versatile"
OPENAI_MODEL = "gpt-4.1-mini"

EXPRESSOES_BLOQUEADAS = [
    'meu bem', 'querida', 'querido', 'meu amor',
    'minha flor', 'benzinho', 'amor da minha vida',
    'meu anjo', 'meu dengo'
]

FONTES = [
    'dia_semana', 'fase_lua', 'ascendente', 'meio_ceu',
    'profissao_contexto', 'reflexao_existencial', 'estacao_clima',
    'micro_momento', 'metafora_criativa', 'aniversario', 'feriado'
]

TONS = [
    {'id': 'sabio_sereno', 'nome': 'Sábio e Sereno', 'descricao': 'Contemplativo, metáforas naturais'},
    {'id': 'energico_motivador', 'nome': 'Enérgico e Motivador', 'descricao': 'Direto, vibrante, ação'},
    {'id': 'leve_humorado', 'nome': 'Leve e Bem-humorado', 'descricao': 'Coloquial, brincalhão'},
    {'id': 'profundo_transformador', 'nome': 'Profundo e Transformador', 'descricao': 'Terapêutico, cura'},
    {'id': 'afetuoso_acolhedor', 'nome': 'Afetuoso e Acolhedor', 'descricao': 'Carinhoso, autocuidado'},
    {'id': 'provocativo_instigante', 'nome': 'Provocativo e Instigante', 'descricao': 'Perguntas, desafia'}
]

DIAS_SEMANA = [
    {'nome': 'Segunda', 'planeta': 'Lua', 'energia': 'emoções, intuição, recomeço'},
    {'nome': 'Terça', 'planeta': 'Marte', 'energia': 'ação, coragem, iniciativa'},
    {'nome': 'Quarta', 'planeta': 'Mercúrio', 'energia': 'comunicação, negócios, ideias'},
    {'nome': 'Quinta', 'planeta': 'Júpiter', 'energia': 'expansão, abundância, visão'},
    {'nome': 'Sexta', 'planeta': 'Vênus', 'energia': 'amor, beleza, conexões'},
    {'nome': 'Sábado', 'planeta': 'Saturno', 'energia': 'estrutura, responsabilidade, foco'},
    {'nome': 'Domingo', 'planeta': 'Sol', 'energia': 'vitalidade, criatividade, descanso'},
]

SYSTEM_PROMPT = "Você é um mentor inspiracional que gera mensagens diárias personalizadas. Responda APENAS com JSON válido."

# ============================================================================
# DADOS ASTRONÔMICOS (via astro_engine / Kerykeion)
# ============================================================================

def _obter_dados_astronomicos() -> Dict[str, Any]:
    """
    Usa o astro_engine (Kerykeion) para obter dados astronômicos reais.
    Mesmo método usado pelo endpoint /hoje.
    """
    try:
        fuso = pytz.timezone("America/Sao_Paulo")
        agora = datetime.now(fuso)

        # Criar sujeito para o momento atual (São Paulo como referência)
        sujeito = gerar_sujeito_final(
            "CeuHoje",
            agora.year, agora.month, agora.day, agora.hour, agora.minute,
            -23.5505, -46.6333,  # São Paulo coords
            "São Paulo", "BR"
        )

        # Calcular fase lunar via Kerykeion (posições reais Sol/Lua)
        fase_lua = calcular_fase_lunar(sujeito)

        if fase_lua:
            # Determinar fase simplificada para a lógica de transição
            fase_nome = fase_lua.get('nome', '').lower()
            if 'nova' in fase_nome:
                fase_simpl = 'nova'
            elif 'cheia' in fase_nome:
                fase_simpl = 'cheia'
            elif 'crescente' in fase_nome:
                fase_simpl = 'crescente'
            else:
                fase_simpl = 'minguante'

            # Calcular ontem para detectar transição
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

            # Extrair iluminação (vem como "85%")
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

    # Fallback mínimo se Kerykeion falhar
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
# UTILITÁRIOS
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
# PROMPT v3.0
# ============================================================================

def _montar_prompt(
    contexto: Dict[str, Any],
    lua: Dict[str, Any],
    fonte: str,
    tom: Dict[str, str],
    data_atual: datetime,
    tipo: str  # 'personalizada' | 'generica'
) -> str:
    dia_semana = _get_dia_semana(data_atual)

    meses = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
             'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
    dias = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira',
            'sexta-feira', 'sábado', 'domingo']
    data_formatada = f"{dias[data_atual.weekday()]}, {data_atual.day} de {meses[data_atual.month - 1]} de {data_atual.year}"

    if tipo == 'personalizada':
        contexto_bloco = f"""
### Contexto do Usuário
- Nome: {contexto.get('nome', 'Você')}
- Signo Solar: {contexto.get('signoSolar', 'não informado')}
- Signo Lunar: {contexto.get('signoLunar', 'não informado')}
- Ascendente: {contexto.get('ascendente', 'não informado')}
- Meio do Céu: {contexto.get('meioCeu', 'não informado')}
- Idade: {contexto.get('idade', 'não informada')}
- Sexo: {contexto.get('sexo', 'não informado')}
- Profissão: {contexto.get('profissao', 'não informada')}
"""
    else:
        contexto_bloco = """
### Contexto Genérico
Mensagem para público geral, sem personalização.
Use linguagem neutra e universal.
"""

    lua_regra = ''
    if not lua.get('isTransicao'):
        lua_regra = '\n⚠️ REGRA CRÍTICA: NÃO mencione a lua na mensagem! Só mencione quando há transição de fase.'

    expressoes = '\n'.join(f'- "{e}"' for e in EXPRESSOES_BLOQUEADAS)
    nome = contexto.get('nome', 'Você')

    prompt = f"""# GERADOR DE MENSAGEM INSPIRACIONAL v{PROMPT_VERSION}

## MODO: {tipo.upper()}
{contexto_bloco}

## DATA E CONTEXTO TEMPORAL
- Data: {data_formatada}
- Dia da Semana: {dia_semana['nome']} (Planeta: {dia_semana['planeta']}, Energia: {dia_semana['energia']})

## LUA DO DIA
- Fase: {lua['fase']} ({lua['faseSimplificada']})
- Signo: {lua['signo']}
- Iluminação: {lua['iluminacao']}%
- Transição de fase hoje: {'SIM ✅' if lua.get('isTransicao') else 'NÃO ❌'}{lua_regra}

## FONTE DE INSPIRAÇÃO SELECIONADA: {fonte.upper().replace('_', ' ')}
Use esta fonte como base principal da mensagem.

## TOM SELECIONADO: {tom['nome'].upper()}
Ajuste a linguagem e abordagem de acordo com este tom.

## REGRAS OBRIGATÓRIAS

### ❌ NUNCA USE estas expressões (soam artificiais vindo de IA):
{expressoes}

### ✅ ABORDAGEM CORRETA:
- Use o nome da pessoa diretamente: "{nome}, hoje..."
- Tom respeitoso mas próximo, como um mentor/amigo sábio
- Evite excesso de carinho forçado

## OUTPUT
Responda APENAS com JSON válido, sem texto adicional:
{{
  "html": "<p>...</p><br><p>...</p>",
  "frase": "..."
}}

Regras do HTML:
- Use <p>, <br>, <strong>, <em>
- Máximo 2 parágrafos curtos (4-8 linhas total)
- 1-2 emojis estratégicos

Regras da Frase:
- Máximo 2 linhas
- Sem emojis
- Pode usar <strong> ou <em>"""

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
    data_atual = datetime.utcnow()
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

                # Buscar MAC
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

                contexto = {
                    'nome': profile.get('nickname') or (profile.get('name', '').split(' ')[0] if profile.get('name') else 'Você'),
                    'signoSolar': mac.get('sol_signo') or mac.get('signo_solar') or 'não informado',
                    'signoLunar': mac.get('lua_signo') or mac.get('signo_lunar'),
                    'ascendente': mac.get('ascendente') or mac.get('ascendente_signo'),
                    'meioCeu': mac.get('meio_ceu') or mac.get('mc_signo'),
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
                .gt('expires_at', datetime.utcnow().isoformat()) \
                .execute()

            existentes = existing_resp.data or []
            if existentes:
                existente = existentes[0]
                # Incrementar visualizações
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

    # ===== OBTER DADOS ASTRONÔMICOS (via Kerykeion / astro_engine) =====
    lua = _obter_dados_astronomicos()

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
    prompt = _montar_prompt(contexto, lua, fonte, tom, data_atual, tipo)

    # ===== CHAMAR LLM COM REGRA POR PLANO =====
    # Free/Trial/Semente → Groq primário, OpenAI fallback
    # Fluxo/Expansão (pagos) → OpenAI primário, Groq fallback
    if is_pago:
        llm_config = {
            "provider": "openai",
            "model": OPENAI_MODEL,
            "fallback_provider": "groq",
            "fallback_model": GROQ_MODEL,
            "temperature": 0.8,
            "max_tokens": MAX_TOKENS
        }
        modelo_usado = OPENAI_MODEL
    else:
        llm_config = {
            "provider": "groq",
            "model": GROQ_MODEL,
            "fallback_provider": "openai",
            "fallback_model": OPENAI_MODEL,
            "temperature": 0.8,
            "max_tokens": MAX_TOKENS
        }
        modelo_usado = GROQ_MODEL

    logger.info(f"[MensagemDia] Gerando para user={user_id}, tipo={tipo}, provider={llm_config['provider']}")

    gateway = LLMGateway.get_instance()
    start_time = datetime.utcnow()

    raw_content = await gateway.generate(
        prompt=prompt,
        config=llm_config,
        system_prompt=SYSTEM_PROMPT
    )

    tempo_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

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
                'diaSemana': _get_dia_semana(data_atual)['nome']
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

        logger.info(f"[MensagemDia] ✓ Salva com sucesso para user={user_id}")
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
            'provider': llm_config['provider']
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
