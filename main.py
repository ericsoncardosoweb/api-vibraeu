from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from kerykeion import KrInstance, MakeSvgInstance
from geopy.geocoders import Nominatim

app = FastAPI()

# Configuração do Geocoding (Converter cidade em Lat/Long)
geolocator = Nominatim(user_agent="meu_app_astrologia")

class DadosNascimento(BaseModel):
    nome: str
    ano: int
    mes: int
    dia: int
    hora: int
    minuto: int
    cidade: str
    pais: str = "BR" # Padrão Brasil, mas pode mudar

@app.post("/gerar-mapa")
async def gerar_mapa(dados: DadosNascimento):
    try:
        # 1. Descobrir Latitude e Longitude pelo nome da cidade
        localizacao = geolocator.geocode(f"{dados.cidade}, {dados.pais}")
        
        if not localizacao:
            raise HTTPException(status_code=404, detail="Cidade não encontrada")
            
        lat = localizacao.latitude
        lng = localizacao.longitude
        timezone = "America/Sao_Paulo" # Simplificação. Para produção, ideal usar biblioteca 'timezonefinder'

        # 2. Calcular o Mapa Astral (Kerykeion)
        usuario = KrInstance(
            dados.nome, 
            dados.ano, dados.mes, dados.dia, 
            dados.hora, dados.minuto,
            lng=lng, lat=lat, 
            tz_str=timezone
        )

        # 3. Gerar a Imagem (SVG)
        # Isso salva o arquivo na pasta onde o script está rodando
        mapa_visual = MakeSvgInstance(usuario, chart_type="Natal")
        mapa_visual.makeSVG()
        nome_arquivo = f"{dados.nome}_Natal.svg" # O Kerykeion salva com esse padrão
        
        # 4. Extrair posições dos planetas nas casas
        planetas = []
        for planeta in usuario.planets_list:
            planetas.append({
                "nome": planeta['name'],
                "signo": planeta['sign'],
                "casa": planeta['house'],
                "grau": planeta['position']
            })

        return {
            "status": "sucesso",
            "dados_entrada": {
                "cidade_detectada": localizacao.address,
                "latitude": lat,
                "longitude": lng
            },
            "posicoes": planetas,
            "casas": usuario.houses_list,
            "ascendente": usuario.first_house,
            "arquivo_imagem": nome_arquivo # Em produção, você retornaria a URL completa
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Rota de teste simples
@app.get("/")
def read_root():
    return {"mensagem": "API de Astrologia rodando!"}