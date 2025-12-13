from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from kerykeion import AstrologicalSubject
from kerykeion.charts.chart_drawer import ChartDrawer
from geopy.geocoders import Nominatim
from pathlib import Path
import os

app = FastAPI(title="API Astrologia VibraEu")

# Configurar Pastas
PASTA_IMAGENS = "mapas_gerados"
os.makedirs(PASTA_IMAGENS, exist_ok=True)
app.mount("/imagens", StaticFiles(directory=PASTA_IMAGENS), name="imagens")

# --- CORREÇÃO AQUI ---
# Adicionei 'timeout=10' para ele esperar até 10 segundos pela resposta do mapa
geolocator = Nominatim(user_agent="vibraeu_astrologia_app_v5", timeout=10)
# ---------------------

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

def criar_sujeito(dados: Pessoa):
    try:
        # Busca lat/long
        loc = geolocator.geocode(f"{dados.cidade}, {dados.pais}")
        
        # Se falhar ou não achar, usamos coordenadas padrão de SP para não travar o app
        # (Isso é uma segurança extra)
        if not loc:
            lat, lng = -23.55, -46.63 # SP Padrão
            print(f"Aviso: Cidade {dados.cidade} não encontrada, usando padrão SP.")
        else:
            lat, lng = loc.latitude, loc.longitude
        
        return AstrologicalSubject(
            dados.nome,
            dados.ano, dados.mes, dados.dia,
            dados.hora, dados.minuto,
            lng=lng,
            lat=lat,
            tz_str="America/Sao_Paulo",
            city=dados.cidade,
            nation=dados.pais
        )
    except Exception as e:
        print(f"Erro ao criar sujeito: {e}")
        # Retorna um erro legível se algo quebrar
        raise HTTPException(status_code=400, detail=f"Erro no cálculo: {str(e)}")

@app.post("/mapa-natal")
async def gerar_natal(dados: Pessoa):
    try:
        sujeito = criar_sujeito(dados)
        nome_safe = "".join([c for c in dados.nome if c.isalnum() or c==' ']).replace(" ", "_")
        nome_arquivo = f"Natal_{nome_safe}"
        
        # Gera o Desenho em Português
        drawer = ChartDrawer(sujeito, chart_language="PT")
        drawer.save_svg(output_directory=PASTA_IMAGENS, filename=nome_arquivo)
        
        planetas_formatados = []
        lista_corpos = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto"]
        
        for corpo in lista_corpos:
            p = sujeito.get(corpo)
            if p:
                planetas_formatados.append({
                    "planeta": corpo,
                    "signo": p.get("sign"),
                    "casa": p.get("house"),
                    "grau": f"{p.get('position'):.2f}"
                })

        return {
            "tipo": "Natal",
            "url_imagem": f"/imagens/{nome_arquivo}.svg",
            "dados_planetas": planetas_formatados
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mapa-sinastria")
async def gerar_sinastria(dados: DadosSinastria):
    p1 = criar_sujeito(dados.pessoa1)
    p2 = criar_sujeito(dados.pessoa2)
    nome_arquivo = f"Sinastria_{dados.pessoa1.nome}_{dados.pessoa2.nome}".replace(" ", "_")
    
    drawer = ChartDrawer(p1, chart_type="Synastry", chart_language="PT", second_obj=p2)
    drawer.save_svg(output_directory=PASTA_IMAGENS, filename=nome_arquivo)
    
    return {"tipo": "Sinastria", "url_imagem": f"/imagens/{nome_arquivo}.svg"}

@app.get("/")
def home():
    return {"status": "online", "metodo": "docker", "mensagem": "API Rodando com Timeout corrigido!"}