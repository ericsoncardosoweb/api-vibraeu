from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from kerykeion import AstrologicalSubjectFactory
from kerykeion.chart_data_factory import ChartDataFactory
from kerykeion.charts.chart_drawer import ChartDrawer
from geopy.geocoders import Nominatim
from pathlib import Path
import os
import json

app = FastAPI(title="API Astrologia VibraEu")

# --- CONFIGURAÇÕES ---
PASTA_IMAGENS = "mapas_gerados"
os.makedirs(PASTA_IMAGENS, exist_ok=True)
app.mount("/imagens", StaticFiles(directory=PASTA_IMAGENS), name="imagens")

geolocator = Nominatim(user_agent="vibraeu_astrologia_app_v5", timeout=10)

# --- MODELOS ---
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

# --- FUNÇÕES AUXILIARES ---
def criar_sujeito(dados: Pessoa):
    try:
        loc = geolocator.geocode(f"{dados.cidade}, {dados.pais}")
        if not loc:
            lat, lng = -23.55, -46.63 
            print(f"Aviso: Cidade {dados.cidade} não encontrada. Usando SP.")
        else:
            lat, lng = loc.latitude, loc.longitude
        
        # Factory padrão da V5
        return AstrologicalSubjectFactory.from_birth_data(
            name=dados.nome,
            year=dados.ano, month=dados.mes, day=dados.dia,
            hour=dados.hora, minute=dados.minuto,
            lng=lng, lat=lat,
            tz_str="America/Sao_Paulo",
            online=False
        )
    except Exception as e:
        print(f"Erro ao criar sujeito: {e}")
        raise HTTPException(status_code=400, detail=f"Erro no cálculo: {str(e)}")

# --- ROTAS ---

@app.post("/mapa-natal")
async def gerar_natal(dados: Pessoa):
    try:
        # 1. Cria o Sujeito
        sujeito = criar_sujeito(dados)
        
        # 2. Gera os Dados do Gráfico
        chart_data = ChartDataFactory.create_natal_chart_data(sujeito)
        
        # 3. Desenha e Salva
        nome_arquivo = f"Natal_{dados.nome.replace(' ', '_')}"
        drawer = ChartDrawer(chart_data=chart_data, chart_language="PT")
        drawer.save_svg(output_path=Path(PASTA_IMAGENS), filename=nome_arquivo)
        
        # --- EXTRAÇÃO DE DADOS (CORRIGIDA) ---
        
        # A. Planetas
        lista_corpos = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", 
                        "Saturn", "Uranus", "Neptune", "Pluto", "Chiron", 
                        "North_Node", "South_Node", "Lilith"]
        
        dados_planetas = []
        for nome_corpo in lista_corpos:
            obj = getattr(sujeito, nome_corpo.lower(), None) # Pega sun, moon, etc.
            if obj:
                info = obj.model_dump()
                dados_planetas.append({
                    "planeta": info.get("name"),
                    "signo": info.get("sign"),
                    "casa": info.get("house"),
                    "grau_absoluto": info.get("abs_pos"),
                    "grau_no_signo": info.get("position"),
                    "retrogrado": info.get("retrograde"),
                    "elemento": info.get("element"),
                    "emoji": info.get("emoji")
                })

        # B. Casas (CORREÇÃO AQUI: Lista Manual de Atributos)
        # Na V5 não existe houses_list, então acessamos um por um
        lista_casas_attr = ["first_house", "second_house", "third_house", "fourth_house", 
                            "fifth_house", "sixth_house", "seventh_house", "eighth_house", 
                            "ninth_house", "tenth_house", "eleventh_house", "twelfth_house"]
        
        dados_casas = []
        for nome_attr in lista_casas_attr:
            casa_obj = getattr(sujeito, nome_attr, None)
            if casa_obj:
                info = casa_obj.model_dump()
                dados_casas.append({
                    "casa": info.get("name"),
                    "signo": info.get("sign"),
                    "grau": info.get("position"),
                    "grau_absoluto": info.get("abs_pos")
                })

        # C. Aspectos
        dados_aspectos = []
        if hasattr(chart_data, "aspects"):
            for aspecto in chart_data.aspects:
                if hasattr(aspecto, "model_dump"):
                    a_info = aspecto.model_dump()
                else:
                    a_info = aspecto
                
                dados_aspectos.append({
                    "p1": a_info.get("p1_name"),
                    "p2": a_info.get("p2_name"),
                    "tipo": a_info.get("aspect"),
                    "orbe": a_info.get("orb")
                })

        return {
            "status": "sucesso",
            "tipo": "Natal",
            "url_imagem": f"/imagens/{nome_arquivo}.svg",
            "interpretacao_rapida": {
                "sol": sujeito.sun.sign,
                "ascendente": sujeito.first_house.sign,
                "lua": sujeito.moon.sign
            },
            "dados_tecnicos": {
                "planetas": dados_planetas,
                "casas": dados_casas,
                "aspectos": dados_aspectos
            }
        }

    except Exception as e:
        print(f"Erro detalhado: {e}") 
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mapa-sinastria")
async def gerar_sinastria(dados: DadosSinastria):
    try:
        p1 = criar_sujeito(dados.pessoa1)
        p2 = criar_sujeito(dados.pessoa2)
        
        chart_data = ChartDataFactory.create_synastry_chart_data(p1, p2)
        
        nome_arquivo = f"Sinastria_{dados.pessoa1.nome}_{dados.pessoa2.nome}".replace(" ", "_")
        drawer = ChartDrawer(chart_data=chart_data, chart_language="PT")
        drawer.save_svg(output_path=Path(PASTA_IMAGENS), filename=nome_arquivo)
        
        aspectos_sinastria = []
        if hasattr(chart_data, "aspects"):
            for aspecto in chart_data.aspects:
                if hasattr(aspecto, "model_dump"):
                    a_info = aspecto.model_dump()
                    aspectos_sinastria.append({
                        "planeta_1": a_info.get("p1_name"),
                        "planeta_2": a_info.get("p2_name"),
                        "aspecto": a_info.get("aspect"),
                        "orbe": a_info.get("orb")
                    })

        return {
            "tipo": "Sinastria",
            "url_imagem": f"/imagens/{nome_arquivo}.svg",
            "aspectos": aspectos_sinastria
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def home():
    return {"status": "online", "versao": "5.0 Corrigida", "mensagem": "JSON Detalhado Funcionando!"}