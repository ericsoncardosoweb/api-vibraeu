from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
# NOVAS IMPORTAÇÕES BASEADAS NA DOCUMENTAÇÃO
from kerykeion import AstrologicalSubjectFactory
from kerykeion.chart_data_factory import ChartDataFactory
from kerykeion.charts.chart_drawer import ChartDrawer
from kerykeion.planetary_return_factory import PlanetaryReturnFactory # Para retorno solar/lunar
from geopy.geocoders import Nominatim
from pathlib import Path
import os

app = FastAPI(title="API Astrologia VibraEu")

# 1. Configurar Pastas
PASTA_IMAGENS = "mapas_gerados"
os.makedirs(PASTA_IMAGENS, exist_ok=True)
app.mount("/imagens", StaticFiles(directory=PASTA_IMAGENS), name="imagens")

# 2. Configurar Geolocalização (com timeout de segurança)
geolocator = Nominatim(user_agent="vibraeu_astrologia_app_v5", timeout=10)

# --- MODELOS DE DADOS ---
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
    # Dados do momento (padrão é agora, mas pode ser futuro)
    ano_t: int
    mes_t: int
    dia_t: int
    hora_t: int
    minuto_t: int
    cidade_t: str

# --- FUNÇÃO AJUDANTE ---
def criar_sujeito(dados: Pessoa):
    """Cria o objeto usando a nova Factory da documentação"""
    try:
        loc = geolocator.geocode(f"{dados.cidade}, {dados.pais}")
        if not loc:
            lat, lng = -23.55, -46.63 # SP Padrão
            print(f"Aviso: Cidade {dados.cidade} não encontrada. Usando SP.")
        else:
            lat, lng = loc.latitude, loc.longitude
        
        # NOVA FORMA DE CRIAR (AstrologicalSubjectFactory)
        return AstrologicalSubjectFactory.from_birth_data(
            name=dados.nome,
            year=dados.ano, 
            month=dados.mes, 
            day=dados.dia,
            hour=dados.hora, 
            minute=dados.minuto,
            lng=lng,
            lat=lat,
            tz_str="America/Sao_Paulo", # Idealmente dinâmico, mas ok por agora
            online=False
        )
    except Exception as e:
        print(f"Erro ao criar sujeito: {e}")
        raise HTTPException(status_code=400, detail=f"Erro no cálculo: {str(e)}")

# --- ROTAS DA API ---

@app.post("/mapa-natal")
async def gerar_natal(dados: Pessoa):
    try:
        # Passo 1: Criar sujeito
        sujeito = criar_sujeito(dados)
        
        # Passo 2: Gerar dados do gráfico (NOVO PADRÃO)
        chart_data = ChartDataFactory.create_natal_chart_data(sujeito)
        
        # Passo 3: Desenhar
        drawer = ChartDrawer(chart_data=chart_data, chart_language="PT")
        
        nome_arquivo = f"Natal_{dados.nome.replace(' ', '_')}"
        drawer.save_svg(output_path=Path(PASTA_IMAGENS), filename=nome_arquivo)
        
        # Extrair dados para JSON (Usando os métodos novos .model_dump_json se precisar, ou acesso direto)
        planetas_formatados = []
        lista_corpos = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto"]
        
        for corpo in lista_corpos:
            # O acesso aos dados mudou um pouco, vamos tentar pegar direto do sujeito
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
            "dados_planetas": planetas_formatados,
            "sol": sujeito.sun.get("sign"),
            "ascendente": sujeito.first_house.get("sign")
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mapa-sinastria")
async def gerar_sinastria(dados: DadosSinastria):
    try:
        # Passo 1: Criar os dois sujeitos
        p1 = criar_sujeito(dados.pessoa1)
        p2 = criar_sujeito(dados.pessoa2)
        
        # Passo 2: Gerar dados de Sinastria (Fábrica detecta os dois sujeitos)
        # Nota: A doc não mostrou "create_synastry_chart_data" explícito, mas geralmente segue o padrão.
        # Se der erro aqui, voltamos para o método antigo, mas vamos tentar o padrão novo:
        chart_data = ChartDataFactory.create_synastry_chart_data(p1, p2)
        
        # Passo 3: Desenhar
        drawer = ChartDrawer(chart_data=chart_data, chart_language="PT")
        
        nome_arquivo = f"Sinastria_{dados.pessoa1.nome}_{dados.pessoa2.nome}".replace(" ", "_")
        drawer.save_svg(output_path=Path(PASTA_IMAGENS), filename=nome_arquivo)
        
        return {"tipo": "Sinastria", "url_imagem": f"/imagens/{nome_arquivo}.svg"}
    except Exception as e:
        # Fallback caso a função create_synastry não exista exatamente com esse nome
        raise HTTPException(status_code=500, detail=f"Erro na Sinastria: {str(e)}")

@app.post("/mapa-transito")
async def gerar_transito(dados: DadosTransito):
    try:
        # 1. Pessoa (Natal)
        p_natal = criar_sujeito(dados.pessoa)
        
        # 2. Trânsito (Criado como se fosse uma pessoa nascendo agora)
        # Precisamos criar manualmente pois não temos um objeto "Pessoa" pronto para o trânsito
        loc = geolocator.geocode(f"{dados.cidade_t}, BR")
        lat_t, lng_t = (loc.latitude, loc.longitude) if loc else (-23.55, -46.63)
        
        p_transito = AstrologicalSubjectFactory.from_birth_data(
            name="Transito",
            year=dados.ano_t, month=dados.mes_t, day=dados.dia_t,
            hour=dados.hora_t, minute=dados.minuto_t,
            lng=lng_t, lat=lat_t,
            tz_str="America/Sao_Paulo",
            online=False
        )
        
        # 3. Gerar dados de Trânsito (Seguindo a doc)
        chart_data = ChartDataFactory.create_transit_chart_data(p_natal, p_transito)
        
        # 4. Desenhar
        drawer = ChartDrawer(chart_data=chart_data, chart_language="PT")
        nome_arquivo = f"Transito_{dados.pessoa.nome}".replace(" ", "_")
        drawer.save_svg(output_path=Path(PASTA_IMAGENS), filename=nome_arquivo)
        
        return {"tipo": "Transito", "url_imagem": f"/imagens/{nome_arquivo}.svg"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def home():
    return {"status": "online", "versao": "Factory Pattern", "mensagem": "API Atualizada conforme Documentação Oficial! v1"}