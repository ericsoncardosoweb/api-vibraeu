"""
Astro Engine Service - Wrapper para Kerykeion.
Lógica extraída fielmente do main.py monolítico original.
Todas as funções preservadas sem alteração de comportamento.
"""

try:
    # Kerykeion v5.0+ — Factory-based API
    from kerykeion import AstrologicalSubjectFactory
    KERYKEION_V5 = True
except ImportError:
    # Fallback v4.x — AstrologicalSubject direto
    from kerykeion import AstrologicalSubject
    KERYKEION_V5 = False

try:
    from kerykeion.chart_data_factory import ChartDataFactory
except ImportError:
    from kerykeion import ChartDataFactory

try:
    from kerykeion.charts.chart_drawer import ChartDrawer
except ImportError:
    from kerykeion import ChartDrawer
from geopy.geocoders import Nominatim
from pathlib import Path
from loguru import logger
import os
import glob

# Timeout aumentado para garantir que o OSM responda
geolocator = Nominatim(user_agent="vibraeu_astrologia_v6", timeout=15)


def gerar_sujeito_final(nome, ano, mes, dia, hora, minuto, lat, lng, cidade_nome, pais_nome):
    """
    Função única que cria o objeto Kerykeion garantindo que o nome da cidade
    apareça certo no gráfico (Corrigindo o bug de Greenwich)
    """
    if KERYKEION_V5:
        return AstrologicalSubjectFactory.from_birth_data(
            name=nome,
            year=ano, month=mes, day=dia,
            hour=hora, minute=minuto,
            lng=lng, lat=lat,
            tz_str="America/Sao_Paulo",
            city=cidade_nome,
            nation=pais_nome,
            online=False
        )
    else:
        # Fallback v4.x
        return AstrologicalSubject(
            nome, ano, mes, dia, hora, minuto,
            lng=lng, lat=lat,
            tz_str="America/Sao_Paulo",
            city=cidade_nome,
            nation=pais_nome,
            online=False
        )


# ============================================================================
# Mapeamentos astrológicos para cálculos de elementos/qualidades
# ============================================================================

SIGNO_ELEMENTO = {
    "Ari": "Fogo", "Tau": "Terra", "Gem": "Ar", "Can": "Água",
    "Leo": "Fogo", "Vir": "Terra", "Lib": "Ar", "Sco": "Água",
    "Sag": "Fogo", "Cap": "Terra", "Aqu": "Ar", "Pis": "Água"
}

SIGNO_QUALIDADE = {
    "Ari": "Cardinal", "Tau": "Fixo", "Gem": "Mutável", "Can": "Cardinal",
    "Leo": "Fixo", "Vir": "Mutável", "Lib": "Cardinal", "Sco": "Fixo",
    "Sag": "Mutável", "Cap": "Cardinal", "Aqu": "Fixo", "Pis": "Mutável"
}

# Pesos: Sol/Lua=2, pessoais=4, geracionais=1 (consistente com alinhamento_service)
PESOS_PLANETAS = {
    "Sun": 2, "Moon": 2,
    "Mercury": 4, "Venus": 4, "Mars": 4,
    "Jupiter": 4, "Saturn": 4,
    "Uranus": 1, "Neptune": 1, "Pluto": 1
}


def _calcular_elementos(dados_planetas, asc_signo, mc_signo):
    """Calcula distribuição percentual dos 4 elementos (Fogo/Terra/Ar/Água)."""
    soma = {"Fogo": 0, "Terra": 0, "Ar": 0, "Água": 0}

    for p in dados_planetas:
        peso = PESOS_PLANETAS.get(p.get("planeta"), 0)
        elemento = SIGNO_ELEMENTO.get(p.get("signo"))
        if peso and elemento:
            soma[elemento] += peso

    # ASC e MC contribuem com 0.5 cada
    asc_el = SIGNO_ELEMENTO.get(asc_signo)
    if asc_el:
        soma[asc_el] += 0.5
    mc_el = SIGNO_ELEMENTO.get(mc_signo)
    if mc_el:
        soma[mc_el] += 0.5

    total = sum(soma.values())
    if total == 0:
        return None

    resultado = {
        "fogo": round(soma["Fogo"] / total * 100),
        "terra": round(soma["Terra"] / total * 100),
        "ar": round(soma["Ar"] / total * 100),
        "agua": round(soma["Água"] / total * 100),
    }
    resultado["dominante"] = max(resultado, key=resultado.get)
    return resultado


def _calcular_qualidades(dados_planetas, asc_signo, mc_signo):
    """Calcula distribuição percentual das 3 qualidades (Cardinal/Fixo/Mutável)."""
    soma = {"Cardinal": 0, "Fixo": 0, "Mutável": 0}

    for p in dados_planetas:
        peso = PESOS_PLANETAS.get(p.get("planeta"), 0)
        qualidade = SIGNO_QUALIDADE.get(p.get("signo"))
        if peso and qualidade:
            soma[qualidade] += peso

    asc_q = SIGNO_QUALIDADE.get(asc_signo)
    if asc_q:
        soma[asc_q] += 0.5
    mc_q = SIGNO_QUALIDADE.get(mc_signo)
    if mc_q:
        soma[mc_q] += 0.5

    total = sum(soma.values())
    if total == 0:
        return None

    resultado = {
        "cardinal": round(soma["Cardinal"] / total * 100),
        "fixo": round(soma["Fixo"] / total * 100),
        "mutavel": round(soma["Mutável"] / total * 100),
    }
    resultado["dominante"] = max(resultado, key=resultado.get)
    return resultado


def _extrair_aspectos(chart_data):
    """Extrai lista de aspectos do chart_data do Kerykeion."""
    aspectos = []
    try:
        # Kerykeion v5: chart_data tem atributo 'aspects' ou 'natal_aspects'
        raw_aspects = None
        for attr in ("aspects", "natal_aspects", "aspects_list"):
            raw_aspects = getattr(chart_data, attr, None)
            if raw_aspects:
                break

        if not raw_aspects:
            # Tentar via model_dump
            try:
                chart_dict = chart_data.model_dump() if hasattr(chart_data, 'model_dump') else {}
                raw_aspects = chart_dict.get("aspects") or chart_dict.get("natal_aspects") or []
            except Exception:
                raw_aspects = []

        for asp in raw_aspects:
            if hasattr(asp, 'model_dump'):
                asp = asp.model_dump()
            elif not isinstance(asp, dict):
                continue

            # Kerykeion aspect fields: p1_name, p2_name, aspect, orbit, ...
            p1 = asp.get("p1_name") or asp.get("planet1") or asp.get("p1", "")
            p2 = asp.get("p2_name") or asp.get("planet2") or asp.get("p2", "")
            tipo = asp.get("aspect") or asp.get("aspect_name") or asp.get("name", "")
            orbe = asp.get("orbit") or asp.get("orb", 0)

            if p1 and p2 and tipo:
                aspectos.append({
                    "planeta1": p1,
                    "planeta2": p2,
                    "aspecto": tipo,
                    "orbe": round(float(orbe), 2) if orbe else 0
                })
    except Exception as e:
        logger.warning(f"Erro ao extrair aspectos: {e}")

    return aspectos


def extrair_dados_tecnicos(sujeito, chart_data):
    """
    Extrai dados técnicos completos do mapa natal.
    
    Retorna:
        planetas, casas, aspectos, elementos, qualidades,
        ascendente_signo, mc_signo
    """
    # Planetas
    lista_corpos = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", 
                    "Saturn", "Uranus", "Neptune", "Pluto", "Chiron", 
                    "North_Node", "Lilith"]
    dados_planetas = []
    for nome_corpo in lista_corpos:
        obj = getattr(sujeito, nome_corpo.lower(), None)
        if obj:
            info = obj.model_dump()
            dados_planetas.append({
                "planeta": info.get("name"),
                "signo": info.get("sign"),
                "casa": info.get("house"),
                "grau_formatado": f"{int(info.get('position'))}° {info.get('sign')}",
                "retrogrado": info.get("retrograde"),
                "emoji": info.get("emoji")
            })
    
    # Casas
    lista_casas = ["first_house", "second_house", "third_house", "fourth_house", 
                   "fifth_house", "sixth_house", "seventh_house", "eighth_house", 
                   "ninth_house", "tenth_house", "eleventh_house", "twelfth_house"]
    dados_casas = []
    for i, nome_attr in enumerate(lista_casas):
        casa_obj = getattr(sujeito, nome_attr, None)
        if casa_obj:
            info = casa_obj.model_dump()
            dados_casas.append({
                "casa": i + 1,
                "signo": info.get("sign"),
                "grau": f"{info.get('position'):.2f}"
            })

    # Campos nomeados: ASC (Casa 1) e MC (Casa 10)
    asc_signo = dados_casas[0]["signo"] if len(dados_casas) >= 1 else None
    mc_signo = dados_casas[9]["signo"] if len(dados_casas) >= 10 else None

    # Aspectos
    aspectos = _extrair_aspectos(chart_data)

    # Elementos e Qualidades
    elementos = _calcular_elementos(dados_planetas, asc_signo, mc_signo)
    qualidades = _calcular_qualidades(dados_planetas, asc_signo, mc_signo)

    return {
        "planetas": dados_planetas,
        "casas": dados_casas,
        "aspectos": aspectos,
        "elementos": elementos,
        "qualidades": qualidades,
        "ascendente_signo": asc_signo,
        "mc_signo": mc_signo
    }


def gerar_mapa_svg(chart_data, pasta_imagens: str, nome_arquivo: str) -> str:
    """
    Gera o arquivo SVG do mapa usando ChartDrawer.
    Retorna o caminho completo do arquivo gerado.
    """
    drawer = ChartDrawer(chart_data=chart_data, chart_language="PT")
    drawer.save_svg(output_path=Path(pasta_imagens), filename=nome_arquivo)
    return os.path.join(pasta_imagens, f"{nome_arquivo}.svg")


def geocode_cidade(cidade: str, estado: str, pais: str = "BR"):
    """
    Busca coordenadas via OpenStreetMap (Nominatim).
    Retorna (lat, lng, display_name) ou fallback para Brasília.
    """
    query = f"{cidade}, {estado}, {pais}"
    logger.info(f"Buscando no mapa: {query}")
    
    loc = geolocator.geocode(query)
    
    if not loc:
        logger.warning(f"Cidade não encontrada: {query}, usando Brasília como fallback")
        return -15.7801, -47.9292, f"{cidade} (Não achada)", None
    
    return loc.latitude, loc.longitude, f"{cidade} - {estado}", loc.address


def calcular_fase_lunar(sujeito):
    """
    Calcula a fase da lua usando as posições reais do Sol e da Lua
    obtidas do Kerykeion (mais preciso que cálculo por ciclo de 29.53 dias).
    """
    try:
        sun_obj = getattr(sujeito, 'sun', None)
        moon_obj = getattr(sujeito, 'moon', None)
        
        if not sun_obj or not moon_obj:
            return None
        
        sun_info = sun_obj.model_dump()
        moon_info = moon_obj.model_dump()
        
        # Posição absoluta em graus (0-360)
        sun_abs = sun_info.get('abs_pos', 0)
        moon_abs = moon_info.get('abs_pos', 0)
        
        # Ângulo entre Lua e Sol (sentido anti-horário)
        angulo = (moon_abs - sun_abs) % 360
        
        # Porcentagem de iluminação aproximada
        iluminacao = round((1 - abs(angulo - 180) / 180) * 100)
        
        # Determinar fase
        if angulo < 45:
            fase = "Lua Nova"
            emoji = "🌑"
            verbo = "plantar"
        elif angulo < 90:
            fase = "Crescente"
            emoji = "🌒"
            verbo = "agir"
        elif angulo < 135:
            fase = "Quarto Crescente"
            emoji = "🌓"
            verbo = "decidir"
        elif angulo < 180:
            fase = "Gibosa Crescente"
            emoji = "🌔"
            verbo = "refinar"
        elif angulo < 225:
            fase = "Lua Cheia"
            emoji = "🌕"
            verbo = "celebrar"
        elif angulo < 270:
            fase = "Gibosa Minguante"
            emoji = "🌖"
            verbo = "agradecer"
        elif angulo < 315:
            fase = "Quarto Minguante"
            emoji = "🌗"
            verbo = "soltar"
        else:
            fase = "Minguante"
            emoji = "🌘"
            verbo = "descansar"
        
        return {
            "nome": fase,
            "emoji": emoji,
            "verbo": verbo,
            "angulo": round(angulo, 1),
            "iluminacao_aprox": f"{iluminacao}%",
            "lua_signo": moon_info.get("sign"),
            "lua_grau": f"{int(moon_info.get('position', 0))}° {moon_info.get('sign', '')}"
        }
    except Exception as e:
        logger.warning(f"Erro ao calcular fase lunar: {e}")
        return None


# --- FUNÇÕES DE LIMPEZA ---

def limpar_arquivos_usuario(pasta: str, user_id: str, prefixo: str = ""):
    """
    Remove arquivos antigos de um usuário específico.
    Busca por padrão: {prefixo}*{user_id}*
    """
    if not user_id or user_id == "unknown":
        return 0
    
    padrao = os.path.join(pasta, f"{prefixo}*{user_id}*")
    arquivos = glob.glob(padrao)
    count = 0
    for arquivo in arquivos:
        try:
            os.remove(arquivo)
            count += 1
            logger.debug(f"Removido: {arquivo}")
        except Exception as e:
            logger.warning(f"Erro ao remover {arquivo}: {e}")
    return count


def limpar_mapas_usuario(pasta_imagens: str, user_id: str):
    """Remove todos os mapas de um usuário"""
    return limpar_arquivos_usuario(pasta_imagens, user_id)


def limpar_avatars_usuario(pasta_avatars: str, user_id: str):
    """Remove todos os avatars de um usuário"""
    return limpar_arquivos_usuario(pasta_avatars, user_id)


def limpar_tudo_usuario(pasta_imagens: str, pasta_avatars: str, user_id: str):
    """Remove todos os arquivos de um usuário (mapas + avatars)"""
    mapas = limpar_mapas_usuario(pasta_imagens, user_id)
    avatars = limpar_avatars_usuario(pasta_avatars, user_id)
    return {"mapas_removidos": mapas, "avatars_removidos": avatars}
