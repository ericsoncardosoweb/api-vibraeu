from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from kerykeion import AstrologicalSubject, KerykeionChartCalculation, AstrologicalSubject
from kerykeion.charts.chart_drawer import ChartDrawer
from kerykeion.charts.chart_data_factory import ChartDataFactory
from geopy.geocoders import Nominatim
from pathlib import Path
import os

app = FastAPI(title="API Astrologia VibraEu")

# Configuração de Pastas para salvar imagens
PASTA_IMAGENS = "mapas_gerados"
os.makedirs(PASTA_IMAGENS, exist_ok=True)

# Servir a pasta de imagens para você conseguir ver os SVGs no navegador
app.mount("/imagens", StaticFiles(directory=PASTA_IMAGENS), name="imagens")

# Configuração do Geocoding (Converter cidade em coordenadas)
geolocator = Nominatim(user_agent="vibraeu_astrologia_app")

# --- MODELOS DE DADOS (O que o usuário envia) ---

class Pessoa(BaseModel):
    nome: str
    ano: int
    mes: int
    dia: int
    hora: int
    minuto: int
    cidade: str
    pais: str = "BR"

class DadosSinastria(BaseModel):
    pessoa1: Pessoa
    pessoa2: Pessoa

class DadosTransito(BaseModel):
    pessoa: Pessoa
    # Para trânsito, usamos a data de "agora" ou uma data futura
    ano_transito: int
    mes_transito: int
    dia_transito: int
    hora_transito: int = 12
    minuto_transito: int = 0
    cidade_transito: str = "São Paulo" # Onde a pessoa está hoje

# --- FUNÇÃO AJUDANTE (Para não repetir código) ---
def criar_sujeito(dados: Pessoa):
    """Cria um objeto AstrologicalSubject convertendo cidade em Lat/Long"""
    try:
        loc = geolocator.geocode(f"{dados.cidade}, {dados.pais}")
        if not loc:
            raise ValueError(f"Cidade não encontrada: {dados.cidade}")
        
        return AstrologicalSubject(
            dados.nome,
            dados.ano, dados.mes, dados.dia,
            dados.hora, dados.minuto,
            lng=loc.longitude,
            lat=loc.latitude,
            tz_str="America/Sao_Paulo", # Idealmente usar timezonefinder
            city=dados.cidade,
            nation=dados.pais
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- ROTAS DA API ---

@app.post("/mapa-natal")
async def gerar_natal(dados: Pessoa):
    """Gera o Mapa Astral de Nascimento (Natal)"""
    sujeito = criar_sujeito(dados)
    
    # Gera os dados
    factory = ChartDataFactory(sujeito)
    dados_mapa = factory.create()
    
    # Desenha o Gráfico (Com idioma PT)
    nome_arquivo = f"Natal_{dados.nome.replace(' ', '_')}"
    drawer = ChartDrawer(sujeito, chart_language="PT") # AQUI ESTÁ A MÁGICA DO IDIOMA
    arquivo_salvo = drawer.save_svg(output_directory=PASTA_IMAGENS, filename=nome_arquivo)
    
    return {
        "tipo": "Natal",
        "url_imagem": f"/imagens/{nome_arquivo}.svg",
        "signo_solar": sujeito.sun["sign"],
        "ascendente": sujeito.first_house["sign"],
        "lua": sujeito.moon["sign"],
        "casas": sujeito.houses_list,
        "planetas": sujeito.planets_list
    }

@app.post("/mapa-transito")
async def gerar_transito(dados: DadosTransito):
    """Gera o Mapa de Trânsito (Influências de hoje sobre o mapa natal)"""
    # 1. Cria a pessoa (Natal)
    p_natal = criar_sujeito(dados.pessoa)
    
    # 2. Cria o momento do Trânsito (Como se fosse uma pessoa nascendo agora)
    loc_transito = geolocator.geocode(f"{dados.cidade_transito}, BR")
    p_transito = AstrologicalSubject(
        "Transito Agora",
        dados.ano_transito, dados.mes_transito, dados.dia_transito,
        dados.hora_transito, dados.minuto_transito,
        lng=loc_transito.longitude,
        lat=loc_transito.latitude,
        tz_str="America/Sao_Paulo",
        city=dados.cidade_transito
    )

    # 3. Desenha o Gráfico de Trânsito (Anel externo girando sobre o interno)
    nome_arquivo = f"Transito_{dados.pessoa.nome.replace(' ', '_')}"
    drawer = ChartDrawer(p_natal, chart_type="Transit", chart_language="PT", second_obj=p_transito)
    drawer.save_svg(output_directory=PASTA_IMAGENS, filename=nome_arquivo)

    return {
        "tipo": "Transito",
        "url_imagem": f"/imagens/{nome_arquivo}.svg",
        "info": "O anel externo mostra os planetas hoje, o interno é o nascimento."
    }

@app.post("/mapa-sinastria")
async def gerar_sinastria(dados: DadosSinastria):
    """Gera o Mapa de Sinastria (Compatibilidade Amorosa)"""
    p1 = criar_sujeito(dados.pessoa1)
    p2 = criar_sujeito(dados.pessoa2)
    
    nome_arquivo = f"Sinastria_{dados.pessoa1.nome}_{dados.pessoa2.nome}"
    drawer = ChartDrawer(p1, chart_type="Synastry", chart_language="PT", second_obj=p2)
    drawer.save_svg(output_directory=PASTA_IMAGENS, filename=nome_arquivo)
    
    return {
        "tipo": "Sinastria",
        "url_imagem": f"/imagens/{nome_arquivo}.svg",
        "info": f"Mapa combinando {dados.pessoa1.nome} (interno) e {dados.pessoa2.nome} (externo)"
    }

@app.get("/")
def home():
    return {"mensagem": "API Astrologia V5 Rodando. Use /docs para testar."}