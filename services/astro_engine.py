"""
Astro Engine Service - Wrapper para Kerykeion.
Lógica extraída fielmente do main.py monolítico original.
Todas as funções preservadas sem alteração de comportamento.
"""

from kerykeion import AstrologicalSubjectFactory
from kerykeion.chart_data_factory import ChartDataFactory
from kerykeion.charts.chart_drawer import ChartDrawer
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


def extrair_dados_tecnicos(sujeito, chart_data):
    """Função auxiliar para limpar o código das rotas e extrair JSON"""
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

    return {"planetas": dados_planetas, "casas": dados_casas}


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
