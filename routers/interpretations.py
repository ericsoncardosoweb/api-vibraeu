"""
Router for generating global astro interpretations via LLM.
Endpoint: POST /admin/generate-global-interpretation
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from loguru import logger
import json
import re

from services.llm_gateway import LLMGateway
from services.supabase_client import get_supabase_client

router = APIRouter()

# =============================================
# SYSTEM PROMPT
# =============================================

SYSTEM_PROMPT = """Você é um astrólogo cabalista sábio e profundo, especializado em astrologia evolutiva integrada aos ensinamentos da Cabala. Seu conhecimento une a sabedoria milenar hebraica com a linguagem dos astros para guiar pessoas em seu caminho de autoconhecimento e evolução espiritual.

Princípios que você segue:
- A Cabala ensina que os astros não determinam, mas influenciam — o livre-arbítrio sempre prevalece
- Cada configuração celeste é uma oportunidade de tikun (correção/aprendizado da alma)
- Os planetas são canais de luz espiritual que podemos usar conscientemente
- A evolução acontece quando entendemos e trabalhamos com as energias, não contra elas

Seu tom é:
- Profundo mas acessível
- Inspirador sem ser fantasioso
- Prático com fundamento espiritual
- Acolhedor e empoderador

IMPORTANTE: Sempre retorne respostas em formato JSON válido conforme solicitado. Não use markdown fencing (```json)."""


# =============================================
# CONTEXTOS CABALÍSTICOS
# =============================================

CONTEXTOS_CICLOS = {
    "capricórnio": {"datas": "22/dez a 19/jan", "sefirah": "Binah (Entendimento)", "elemento": "Terra Cardinal", "regente": "Saturno", "tikun": "Equilibrar ambição com compaixão, estrutura com flexibilidade", "temas": "Carreira, autoridade, responsabilidade, maturidade, legado"},
    "aquário": {"datas": "20/jan a 18/fev", "sefirah": "Chokmah (Sabedoria)", "elemento": "Ar Fixo", "regente": "Urano/Saturno", "tikun": "Equilibrar individualidade com pertencimento", "temas": "Inovação, humanidade, liberdade, comunidade, visão de futuro"},
    "peixes": {"datas": "19/fev a 20/mar", "sefirah": "Keter (Coroa)", "elemento": "Água Mutável", "regente": "Netuno/Júpiter", "tikun": "Conectar-se ao divino mantendo os pés no chão", "temas": "Espiritualidade, intuição, compaixão, arte, transcendência"},
    "áries": {"datas": "21/mar a 19/abr", "sefirah": "Chesed (Misericórdia)", "elemento": "Fogo Cardinal", "regente": "Marte", "tikun": "Canalizar força pioneira com consciência", "temas": "Novos começos, coragem, liderança, identidade, impulso vital"},
    "touro": {"datas": "20/abr a 20/mai", "sefirah": "Gevurah (Força)", "elemento": "Terra Fixa", "regente": "Vênus", "tikun": "Encontrar segurança interior, flexibilizar apegos", "temas": "Valores, recursos, prazer sensorial, estabilidade, autovalor"},
    "gêmeos": {"datas": "21/mai a 20/jun", "sefirah": "Tiferet (Beleza)", "elemento": "Ar Mutável", "regente": "Mercúrio", "tikun": "Integrar dualidades, comunicar com propósito", "temas": "Comunicação, aprendizado, conexões, versatilidade, curiosidade"},
    "câncer": {"datas": "21/jun a 22/jul", "sefirah": "Netzach (Vitória)", "elemento": "Água Cardinal", "regente": "Lua", "tikun": "Nutrir sem sufocar, proteger sem controlar", "temas": "Lar, família, emoções, memória, nutrição, raízes"},
    "leão": {"datas": "23/jul a 22/ago", "sefirah": "Hod (Glória)", "elemento": "Fogo Fixo", "regente": "Sol", "tikun": "Brilhar sem ofuscar, liderar com humildade", "temas": "Criatividade, expressão, liderança, generosidade, amor"},
    "virgem": {"datas": "23/ago a 22/set", "sefirah": "Yesod (Fundamento)", "elemento": "Terra Mutável", "regente": "Mercúrio", "tikun": "Servir sem se anular, aperfeiçoar sem criticar", "temas": "Serviço, saúde, rotina, análise, purificação, trabalho"},
    "libra": {"datas": "23/set a 22/out", "sefirah": "Malkuth (Reino)", "elemento": "Ar Cardinal", "regente": "Vênus", "tikun": "Manter identidade nas parcerias, decidir mesmo sem consenso", "temas": "Relacionamentos, equilíbrio, justiça, beleza, harmonia"},
    "escorpião": {"datas": "23/out a 21/nov", "sefirah": "Daath (Conhecimento Oculto)", "elemento": "Água Fixa", "regente": "Plutão/Marte", "tikun": "Transformar sem destruir, mergulhar nas sombras para trazer luz", "temas": "Transformação, poder, intensidade, renascimento, mistérios"},
    "sagitário": {"datas": "22/nov a 21/dez", "sefirah": "Chesed expandido", "elemento": "Fogo Mutável", "regente": "Júpiter", "tikun": "Expandir com responsabilidade, buscar verdade com humildade", "temas": "Expansão, filosofia, viagens, conhecimento superior, significado"},
}

CONTEXTOS_LUA = {
    "nova": {"sefirah": "Binah (Entendimento no Silêncio)", "energia": "Yin máximo, gestação, semente, potencial puro", "tikun": "Confiar no invisível, plantar intenções no escuro, paciência criativa", "pratica": "Meditação silenciosa, definição de intenções, journaling de desejos", "temas": "Novos começos, introspecção, plantio de sementes, silêncio criativo"},
    "crescente": {"sefirah": "Chesed (Expansão Crescente)", "energia": "Yang crescente, movimento, construção, ação", "tikun": "Agir com fé mesmo sem ver resultados, persistir com propósito", "pratica": "Planejamento ativo, primeiros passos concretos, networking", "temas": "Crescimento, ação, construção, compromisso, desenvolvimento"},
    "cheia": {"sefirah": "Tiferet (Iluminação e Plenitude)", "energia": "Yang máximo, revelação, colheita, manifestação plena", "tikun": "Celebrar sem ego, compartilhar a luz, gratidão consciente", "pratica": "Celebração, ritual de gratidão, liberação emocional, partilha", "temas": "Iluminação, revelação, plenitude, celebração, culminação"},
    "minguante": {"sefirah": "Gevurah (Discernimento e Liberação)", "energia": "Yin crescente, reflexão, soltar, integrar", "tikun": "Soltar com graça, perdoar o que ficou incompleto, integrar lições", "pratica": "Limpeza energética, desapego consciente, revisão, perdão", "temas": "Liberação, reflexão, desapego, integração, preparação"},
}

CONTEXTOS_PLANETAS = {
    "sol": {"simbolismo": "Essência, identidade, propósito de vida", "sefirah": "Tiferet — Centro da Árvore da Vida", "tikun": "Brilhar autenticamente, liderar com coração", "transitos": "Ciclo anual — ilumina cada casa por ~30 dias"},
    "lua": {"simbolismo": "Emoções, inconsciente, necessidades, passado", "sefirah": "Yesod — Fundamento emocional", "tikun": "Honrar emoções sem ser dominado por elas", "transitos": "Ciclo de 28 dias — influencia humor e receptividade"},
    "mercúrio": {"simbolismo": "Comunicação, mente, aprendizado, conexões", "sefirah": "Hod — Intelecto e comunicação", "tikun": "Comunicar com verdade e compaixão", "transitos": "Retrógrado 3-4x/ano — revisão e reavaliação"},
    "vênus": {"simbolismo": "Amor, beleza, valores, prazer", "sefirah": "Netzach — Amor e desejo", "tikun": "Amar incondicionalmente, encontrar beleza no imperfeito", "transitos": "Retrógrado a cada 18 meses — revisão de relacionamentos"},
    "marte": {"simbolismo": "Ação, desejo, coragem, força vital", "sefirah": "Gevurah — Força e discernimento", "tikun": "Agir com propósito, coragem consciente", "transitos": "Retrógrado a cada 2 anos — revisão de ações"},
    "júpiter": {"simbolismo": "Expansão, sabedoria, abundância, fé", "sefirah": "Chesed — Misericórdia e expansão", "tikun": "Expandir com responsabilidade, generosidade com discernimento", "transitos": "Ciclo de 12 anos — traz crescimento"},
    "saturno": {"simbolismo": "Estrutura, limites, maturidade, tempo", "sefirah": "Binah — Entendimento através de limites", "tikun": "Aceitar responsabilidade, construir com paciência", "transitos": "Ciclo de 29 anos — traz testes e maturidade"},
    "urano": {"simbolismo": "Revolução, liberdade, originalidade, despertar", "sefirah": "Chokmah — Sabedoria súbita", "tikun": "Libertar-se de padrões limitantes", "transitos": "Ciclo de 84 anos — revoluções e despertares"},
    "netuno": {"simbolismo": "Espiritualidade, intuição, sonhos, transcendência", "sefirah": "Keter — Conexão com o Divino", "tikun": "Conectar-se ao espiritual mantendo discernimento", "transitos": "Ciclo de 165 anos — dissolve ilusões"},
    "plutão": {"simbolismo": "Transformação, poder, morte/renascimento", "sefirah": "Daath — Portal de transformação", "tikun": "Morrer para o ego, renascer em consciência", "transitos": "Ciclo de 248 anos — transformações profundas"},
}

CONTEXTOS_CASAS = {
    "casa_1": {"nome": "Casa 1 — Eu & Identidade", "sefirah": "Keter (A Coroa do Ser)", "regente_natural": "Marte/Áries", "tikun": "Expressar a essência autêntica sem máscara, coragem de ser quem se é", "temas": "Identidade, aparência, primeiras impressões, iniciativa, autoexpressão, corpo físico"},
    "casa_2": {"nome": "Casa 2 — Recursos & Valores", "sefirah": "Chokmah (Sabedoria do Valor)", "regente_natural": "Vênus/Touro", "tikun": "Encontrar segurança interior, reconhecer o verdadeiro valor além do material", "temas": "Finanças, posses, talentos, autoestima, valores pessoais, recursos internos"},
    "casa_3": {"nome": "Casa 3 — Mente & Troca", "sefirah": "Binah (Entendimento Comunicativo)", "regente_natural": "Mercúrio/Gêmeos", "tikun": "Comunicar com propósito, aprender a ouvir tanto quanto falar", "temas": "Comunicação, irmãos, vizinhos, aprendizado, mente racional, escritos, deslocamentos curtos"},
    "casa_4": {"nome": "Casa 4 — Base & Ancestralidade", "sefirah": "Chesed (Misericórdia das Raízes)", "regente_natural": "Lua/Câncer", "tikun": "Curar padrões ancestrais, criar um lar interior seguro independente do externo", "temas": "Lar, família, ancestralidade, base emocional, final de vida, propriedades, mãe/pai"},
    "casa_5": {"nome": "Casa 5 — Criação & Prazer", "sefirah": "Gevurah (Força Criativa)", "regente_natural": "Sol/Leão", "tikun": "Criar sem apego ao resultado, brilhar sem ofuscar, expressar alegria autêntica", "temas": "Criatividade, filhos, romance, prazer, jogos, hobbies, expressão artística, diversão"},
    "casa_6": {"nome": "Casa 6 — Rotina & Saúde", "sefirah": "Tiferet (Beleza no Cotidiano)", "regente_natural": "Mercúrio/Virgem", "tikun": "Sacralizar o cotidiano, servir com amor sem se anular", "temas": "Saúde, trabalho diário, rotina, serviço, animais de estimação, hábitos, purificação"},
    "casa_7": {"nome": "Casa 7 — Parcerias & Espelho", "sefirah": "Netzach (Vitória nas Relações)", "regente_natural": "Vênus/Libra", "tikun": "Ver o outro como espelho, manter identidade nas parcerias, equilibrar dar e receber", "temas": "Casamento, parcerias, contratos, inimigos declarados, relacionamentos, o outro como espelho"},
    "casa_8": {"nome": "Casa 8 — Mudança & Desapego", "sefirah": "Hod (Glória na Transformação)", "regente_natural": "Plutão/Escorpião", "tikun": "Soltar o que já morreu, confiar no processo de transformação, renascer das cinzas", "temas": "Transformação, morte/renascimento, heranças, sexualidade, recursos compartilhados, mistérios, ocultismo"},
    "casa_9": {"nome": "Casa 9 — Sabedoria & Busca", "sefirah": "Yesod (Fundamento da Fé)", "regente_natural": "Júpiter/Sagitário", "tikun": "Expandir com humildade, buscar verdade sem dogmatismo, ser eterno aprendiz", "temas": "Filosofia, ensino superior, viagens longas, espiritualidade, publicações, justiça, mestres"},
    "casa_10": {"nome": "Casa 10 — Propósito & Legado", "sefirah": "Malkuth (Reino da Manifestação)", "regente_natural": "Saturno/Capricórnio", "tikun": "Construir legado com integridade, carregar responsabilidade com sabedoria", "temas": "Carreira, vocação, reputação, status social, conquistas, autoridade, legado, missão de vida"},
    "casa_11": {"nome": "Casa 11 — Coletivo & Causas", "sefirah": "Chokmah Expandido (Sabedoria Coletiva)", "regente_natural": "Urano/Aquário", "tikun": "Equilibrar individualidade com pertencimento, servir ao coletivo mantendo a essência", "temas": "Amizades, grupos, causas sociais, sonhos, projetos futuros, inovação, comunidade, redes"},
    "casa_12": {"nome": "Casa 12 — Alma & Transcendência", "sefirah": "Keter Oculto (A Coroa Invisível)", "regente_natural": "Netuno/Peixes", "tikun": "Conectar-se ao divino sem se perder, integrar sombras, dissolver o ego conscientemente", "temas": "Inconsciente, espiritualidade, isolamento, karma, autossabotagem, compaixão, sonhos, mistérios"},
}


# =============================================
# PROMPT BUILDERS
# =============================================

def build_prompt_ciclo(chave: str) -> str:
    ctx = CONTEXTOS_CICLOS.get(chave.lower())
    if not ctx:
        raise ValueError(f"Contexto não encontrado para ciclo: {chave}")
    
    return f"""Gere uma interpretação astrológica cabalística completa para o CICLO DE {chave.upper()}.

Contexto cabalístico:
- Datas: {ctx['datas']}
- Sefirah: {ctx['sefirah']}
- Elemento: {ctx['elemento']}
- Planeta regente: {ctx['regente']}
- Tikun: {ctx['tikun']}
- Temas principais: {ctx['temas']}

Retorne APENAS um JSON válido com esta estrutura:
{{
  "titulo": "Ciclo de {chave.title()} — [subtítulo criativo e evocativo com 3-5 palavras]",
  "resumo": "[Frase-síntese de até 15 palavras que captura a essência deste ciclo]",
  "leitura_geral": "<HTML com 2-3 parágrafos explicando o que este ciclo representa cosmicamente, suas datas, energia predominante e principais temas. Use <p>, <strong>, <em> para formatação>",
  "o_que_representa": "<HTML com 2-3 parágrafos sobre o significado cabalístico profundo. Qual sefirah está associada? Que tikun esta energia oferece? Quais são as lições espirituais? Use <p>, <strong>, <em>>",
  "frase": "[Frase inspiradora e profunda de até 25 palavras, que as pessoas queiram compartilhar e levar pra vida. Estilo poético-filosófico, sem clichês]"
}}"""


def build_prompt_lua(chave: str) -> str:
    parts = chave.lower().split('_', 1)
    if len(parts) != 2:
        raise ValueError(f"Chave de lua inválida: {chave}. Formato esperado: fase_signo")
    
    fase, signo = parts
    ctx_fase = CONTEXTOS_LUA.get(fase)
    ctx_signo = CONTEXTOS_CICLOS.get(signo)
    
    if not ctx_fase:
        raise ValueError(f"Fase da lua não encontrada: {fase}")
    if not ctx_signo:
        raise ValueError(f"Signo não encontrado: {signo}")
    
    nome_fase = {"nova": "Lua Nova", "crescente": "Lua Crescente", "cheia": "Lua Cheia", "minguante": "Lua Minguante"}[fase]
    
    return f"""Gere uma interpretação astrológica cabalística completa para: {nome_fase} em {signo.title()}.

Contexto da fase lunar:
- Fase: {nome_fase}
- Sefirah da fase: {ctx_fase['sefirah']}
- Energia: {ctx_fase['energia']}
- Tikun da fase: {ctx_fase['tikun']}
- Práticas recomendadas: {ctx_fase['pratica']}
- Temas: {ctx_fase['temas']}

Contexto do signo {signo.title()}:
- Elemento: {ctx_signo['elemento']}
- Regente: {ctx_signo['regente']}
- Sefirah do signo: {ctx_signo['sefirah']}
- Tikun do signo: {ctx_signo['tikun']}
- Temas do signo: {ctx_signo['temas']}

A interpretação deve integrar a FASE LUNAR com o SIGNO, mostrando como a energia da {nome_fase} se manifesta através das qualidades de {signo.title()}.

Retorne APENAS um JSON válido com esta estrutura:
{{
  "titulo": "{nome_fase} em {signo.title()} — [subtítulo criativo e evocativo com 3-5 palavras]",
  "resumo": "[Frase-síntese de até 15 palavras que captura a essência desta combinação lua+signo]",
  "leitura_geral": "<HTML com 2-3 parágrafos explicando como a {nome_fase} em {signo.title()} afeta a energia coletiva. Quais temas surgem? Que oportunidades este momento traz? Como aproveitar? Use <p>, <strong>, <em>>",
  "o_que_representa": "<HTML com 2-3 parágrafos sobre o significado cabalístico desta combinação. Como a sefirah da fase ({ctx_fase['sefirah']}) interage com a do signo ({ctx_signo['sefirah']})? Que tikun emerge desta fusão? Práticas e rituais recomendados. Use <p>, <strong>, <em>>",
  "frase": "[Frase inspiradora e profunda de até 25 palavras sobre esta lua em {signo.title()}, que as pessoas queiram compartilhar. Estilo poético-filosófico, sem clichês]"
}}"""


def build_prompt_planeta(chave: str) -> str:
    ctx = CONTEXTOS_PLANETAS.get(chave.lower())
    if not ctx:
        raise ValueError(f"Planeta não encontrado: {chave}")
    
    return f"""Gere uma interpretação astrológica cabalística completa para o planeta {chave.upper()}.

Contexto cabalístico:
- Simbolismo: {ctx['simbolismo']}
- Sefirah: {ctx['sefirah']}
- Tikun: {ctx['tikun']}
- Trânsitos: {ctx['transitos']}

A interpretação deve explicar o que {chave.title()} representa como arquétipo, seu papel na jornada da alma, como seus trânsitos influenciam a vida, e que lições práticas tirar da sua energia.

Retorne APENAS um JSON válido com esta estrutura:
{{
  "titulo": "{chave.title()} — [subtítulo criativo que captura a essência deste planeta em 3-5 palavras]",
  "resumo": "[Frase-síntese de até 15 palavras sobre o papel de {chave.title()} na jornada evolutiva]",
  "leitura_geral": "<HTML com 2-3 parágrafos explicando o simbolismo de {chave.title()}, como seus trânsitos afetam a vida, e que áreas de vida ilumina. Use <p>, <strong>, <em>>",
  "o_que_representa": "<HTML com 2-3 parágrafos sobre o significado cabalístico de {chave.title()}. Qual sefirah canaliza? Que tikun oferece? Como trabalhar conscientemente com esta energia? Use <p>, <strong>, <em>>",
  "frase": "[Frase inspiradora e profunda de até 25 palavras sobre a energia de {chave.title()}, que as pessoas queiram compartilhar. Estilo poético-filosófico, sem clichês]"
}}"""


def build_prompt_casa(chave: str) -> str:
    ctx = CONTEXTOS_CASAS.get(chave.lower())
    if not ctx:
        raise ValueError(f"Casa não encontrada: {chave}")
    
    numero = chave.lower().replace('casa_', '')
    
    return f"""Gere uma interpretação astrológica cabalística completa para a {ctx['nome']}.

Contexto cabalístico:
- Sefirah: {ctx['sefirah']}
- Regente natural: {ctx['regente_natural']}
- Tikun: {ctx['tikun']}
- Temas principais: {ctx['temas']}

A interpretação deve explicar o que a Casa {numero} representa no mapa astral, qual seu papel na jornada evolutiva da alma, como ela influencia a vida cotidiana, e que aprendizados e práticas espirituais estão associados a esta casa.

Retorne APENAS um JSON válido com esta estrutura:
{{
  "titulo": "{ctx['nome']} — [subtítulo criativo e evocativo com 3-5 palavras]",
  "resumo": "[Frase-síntese de até 15 palavras que captura a essência desta casa astrológica]",
  "leitura_geral": "<HTML com 2-3 parágrafos explicando o que a Casa {numero} representa, quais áreas da vida governa, como seus trânsitos e planetas residentes afetam o cotidiano. Use <p>, <strong>, <em> para formatação>",
  "o_que_representa": "<HTML com 2-3 parágrafos sobre o significado cabalístico profundo. Qual sefirah está associada? Que tikun esta casa oferece? Quais são as lições espirituais e como trabalhar conscientemente com esta energia? Use <p>, <strong>, <em>>",
  "frase": "[Frase inspiradora e profunda de até 25 palavras sobre a energia da Casa {numero}, que as pessoas queiram compartilhar. Estilo poético-filosófico, sem clichês]"
}}"""


PROMPT_BUILDERS = {
    "ciclo": build_prompt_ciclo,
    "lua": build_prompt_lua,
    "planeta": build_prompt_planeta,
    "casa": build_prompt_casa,
}


# =============================================
# REQUEST / RESPONSE MODELS
# =============================================

class GenerateRequest(BaseModel):
    tipo: str  # 'ciclo', 'lua', 'planeta', 'casa'
    chave: str  # 'capricórnio', 'nova_áries', 'sol'


class GenerateResponse(BaseModel):
    success: bool
    tipo: str
    chave: str
    data: Optional[dict] = None
    error: Optional[str] = None


# =============================================
# ENDPOINT
# =============================================

@router.post("/generate-global-interpretation", response_model=GenerateResponse)
async def generate_global_interpretation(request: GenerateRequest):
    """
    Generate a global interpretation for a given type and key.
    Uses OpenAI (GPT-4.1 Mini) as primary LLM with Groq fallback.
    """
    tipo = request.tipo.lower().strip()
    chave = request.chave.lower().strip()
    
    logger.info(f"🔮 Generating global interpretation: {tipo}/{chave}")
    
    # 1. Validate tipo
    if tipo not in PROMPT_BUILDERS:
        raise HTTPException(
            status_code=400, 
            detail=f"Tipo inválido: {tipo}. Valores aceitos: {list(PROMPT_BUILDERS.keys())}"
        )
    
    # 2. Build prompt
    try:
        prompt = PROMPT_BUILDERS[tipo](chave)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # 3. Call LLM
    try:
        llm = LLMGateway.get_instance()
        raw_response = await llm.generate(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            config={
                "temperature": 0.75,
                "max_tokens": 2500,
            }
        )
    except Exception as e:
        logger.error(f"❌ LLM generation failed for {tipo}/{chave}: {e}")
        return GenerateResponse(
            success=False, tipo=tipo, chave=chave,
            error=f"Erro na geração via IA: {str(e)}"
        )
    
    # 4. Parse JSON response
    try:
        # Clean up markdown fencing if present
        cleaned = raw_response.strip()
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
        
        parsed = json.loads(cleaned)
        
        # Validate required fields
        required = ["titulo", "resumo", "leitura_geral", "o_que_representa", "frase"]
        missing = [f for f in required if not parsed.get(f)]
        if missing:
            raise ValueError(f"Campos faltando na resposta: {missing}")
            
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"❌ Failed to parse LLM response for {tipo}/{chave}: {e}")
        logger.debug(f"Raw response: {raw_response[:500]}")
        return GenerateResponse(
            success=False, tipo=tipo, chave=chave,
            error=f"Erro ao processar resposta da IA: {str(e)}"
        )
    
    # 5. Save to Supabase
    try:
        supabase = get_supabase_client()
        
        update_data = {
            "titulo": parsed["titulo"],
            "resumo": parsed["resumo"],
            "leitura_geral": parsed["leitura_geral"],
            "o_que_representa": parsed["o_que_representa"],
            "frase": parsed["frase"],
        }
        
        # Try update first
        result = supabase.table("astro_interpretacoes") \
            .update(update_data) \
            .eq("tipo", tipo) \
            .eq("chave", chave) \
            .execute()
        
        if not result.data:
            # Record doesn't exist — insert
            insert_data = {**update_data, "tipo": tipo, "chave": chave}
            result = supabase.table("astro_interpretacoes") \
                .insert(insert_data) \
                .execute()
        
        logger.info(f"✅ Saved interpretation: {tipo}/{chave}")
        
    except Exception as e:
        logger.error(f"❌ Failed to save {tipo}/{chave}: {e}")
        # Return the data anyway so the user can see what was generated
        return GenerateResponse(
            success=True, tipo=tipo, chave=chave,
            data=parsed, error=f"Gerado mas erro ao salvar: {str(e)}"
        )
    
    return GenerateResponse(
        success=True, tipo=tipo, chave=chave,
        data=parsed
    )
