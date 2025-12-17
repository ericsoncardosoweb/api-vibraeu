from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from kerykeion import AstrologicalSubjectFactory
from kerykeion.chart_data_factory import ChartDataFactory
from kerykeion.charts.chart_drawer import ChartDrawer
from geopy.geocoders import Nominatim
from pathlib import Path
import os
import glob
import uuid
from datetime import datetime
import pytz

app = FastAPI(title="API Astrologia VibraEu - Multi Rotas")

# --- CONFIGURAÇÕES ---
PASTA_IMAGENS = "mapas_gerados"
PASTA_AVATARS = "avatars"  # Simplificado para evitar conflitos
os.makedirs(PASTA_IMAGENS, exist_ok=True)
os.makedirs(PASTA_AVATARS, exist_ok=True)

# Montar pastas estáticas
app.mount("/imagens", StaticFiles(directory=PASTA_IMAGENS), name="imagens")
app.mount("/avatars", StaticFiles(directory=PASTA_AVATARS), name="avatars")

# Timeout aumentado para garantir que o OSM responda
geolocator = Nominatim(user_agent="vibraeu_astrologia_v6", timeout=15)

# --- FUNÇÃO DE LIMPEZA DE ARQUIVOS ---
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
            print(f"Removido: {arquivo}")
        except Exception as e:
            print(f"Erro ao remover {arquivo}: {e}")
    return count

def limpar_mapas_usuario(user_id: str):
    """Remove todos os mapas de um usuário"""
    return limpar_arquivos_usuario(PASTA_IMAGENS, user_id)

def limpar_avatars_usuario(user_id: str):
    """Remove todos os avatars de um usuário"""
    return limpar_arquivos_usuario(PASTA_AVATARS, user_id)

def limpar_tudo_usuario(user_id: str):
    """Remove todos os arquivos de um usuário (mapas + avatars)"""
    mapas = limpar_mapas_usuario(user_id)
    avatars = limpar_avatars_usuario(user_id)
    return {"mapas_removidos": mapas, "avatars_removidos": avatars}

# --- MODELOS DE DADOS (Separados por Estratégia) ---

# 1. Modelo para quem JÁ TEM Latitude/Longitude (Rápido)
class PessoaLL(BaseModel):
    nome: str
    ano: int
    mes: int
    dia: int
    hora: int
    minuto: int
    latitude: float
    longitude: float
    user_id: Optional[str] = None  # NOVO: Para identificar e limpar depois
    # Opcionais apenas para sair escrito no mapa
    cidade_label: str = "Coordenada Personalizada"
    pais_label: str = "BR"

# 2. Modelo para busca por NOME (OpenStreetMap)
class PessoaOSM(BaseModel):
    nome: str
    ano: int
    mes: int
    dia: int
    hora: int
    minuto: int
    cidade: str
    estado: str  # Novo campo para precisão (ex: SP, MG)
    pais: str = "BR"
    user_id: Optional[str] = None  # NOVO: Para identificar e limpar depois

# 3. Modelo para Sinastria (Pode misturar, vamos simplificar pedindo Lat/Long para performance)
class DadosSinastria(BaseModel):
    pessoa1: PessoaLL
    pessoa2: PessoaLL

# 4. Modelo para o Céu de Hoje
class LocalizacaoHoje(BaseModel):
    cidade: str = "Brasília"
    estado: str = "DF"
    pais: str = "BR"

# 5. Modelo para limpeza de dados
class LimpezaRequest(BaseModel):
    user_id: str
    tipo: str = "todos"  # "mapas", "avatars" ou "todos"

# --- FUNÇÃO CENTRAL DE CRIAÇÃO ---
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
        city=cidade_nome,    # AQUI ESTÁ A CORREÇÃO DO NOME
        nation=pais_nome,    # AQUI ESTÁ A CORREÇÃO DO PAÍS
        online=False         # Mantemos false para velocidade, mas passamos os nomes acima
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

# --- ROTAS ---

# ROTA 1: Alta Precisão (Lat/Long)
@app.post("/natal-ll")
async def natal_lat_long(dados: PessoaLL):
    try:
        sujeito = gerar_sujeito_final(
            dados.nome, dados.ano, dados.mes, dados.dia, dados.hora, dados.minuto,
            dados.latitude, dados.longitude, dados.cidade_label, dados.pais_label
        )
        
        chart_data = ChartDataFactory.create_natal_chart_data(sujeito)
        
        # MELHORADO: Nome com user_id para limpeza posterior
        nome_seguro = dados.nome.replace(' ', '_')
        if dados.user_id:
            # Limpar mapa antigo do usuário antes de criar novo
            limpar_arquivos_usuario(PASTA_IMAGENS, dados.user_id, "Natal_LL_")
            nome_arquivo = f"Natal_LL_{nome_seguro}_{dados.user_id}"
        else:
            nome_arquivo = f"Natal_LL_{nome_seguro}"
        
        drawer = ChartDrawer(chart_data=chart_data, chart_language="PT")
        drawer.save_svg(output_path=Path(PASTA_IMAGENS), filename=nome_arquivo)
        
        json_dados = extrair_dados_tecnicos(sujeito, chart_data)
        
        return {
            "tipo": "Natal (Lat/Long)",
            "url_imagem": f"/imagens/{nome_arquivo}.svg",
            "dados": json_dados
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ROTA 2: Busca por Nome (OSM)
@app.post("/natal-osm")
async def natal_busca_cidade(dados: PessoaOSM):
    try:
        # Monta a string de busca: "Sorocaba, SP, BR"
        query = f"{dados.cidade}, {dados.estado}, {dados.pais}"
        print(f"Buscando no mapa: {query}")
        
        loc = geolocator.geocode(query)
        
        if not loc:
            # Fallback de segurança (Brasília) se não achar, para não quebrar
            print("Cidade não encontrada, usando default.")
            lat, lng = -15.7801, -47.9292 
            cidade_display = f"{dados.cidade} (Não achada)"
        else:
            lat, lng = loc.latitude, loc.longitude
            cidade_display = f"{dados.cidade} - {dados.estado}"

        sujeito = gerar_sujeito_final(
            dados.nome, dados.ano, dados.mes, dados.dia, dados.hora, dados.minuto,
            lat, lng, cidade_display, dados.pais
        )
        
        chart_data = ChartDataFactory.create_natal_chart_data(sujeito)
        
        # MELHORADO: Nome com user_id para limpeza posterior
        nome_seguro = dados.nome.replace(' ', '_')
        if dados.user_id:
            # Limpar mapa antigo do usuário antes de criar novo
            limpar_arquivos_usuario(PASTA_IMAGENS, dados.user_id, "Natal_OSM_")
            nome_arquivo = f"Natal_OSM_{nome_seguro}_{dados.user_id}"
        else:
            nome_arquivo = f"Natal_OSM_{nome_seguro}"
        
        drawer = ChartDrawer(chart_data=chart_data, chart_language="PT")
        drawer.save_svg(output_path=Path(PASTA_IMAGENS), filename=nome_arquivo)
        
        json_dados = extrair_dados_tecnicos(sujeito, chart_data)

        return {
            "tipo": "Natal (Busca Nome)",
            "local_encontrado": loc.address if loc else "Default",
            "coords": {"lat": lat, "lng": lng},
            "url_imagem": f"/imagens/{nome_arquivo}.svg",
            "dados": json_dados
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ROTA 3: Céu de Hoje
@app.post("/hoje")
async def ceu_de_hoje(local: LocalizacaoHoje):
    try:
        # Pega hora atual de SP
        fuso = pytz.timezone("America/Sao_Paulo")
        agora = datetime.now(fuso)
        
        # Busca coords da referência (ex: Brasilia)
        query = f"{local.cidade}, {local.estado}, {local.pais}"
        loc = geolocator.geocode(query)
        if loc:
            lat, lng = loc.latitude, loc.longitude
        else:
            lat, lng = -15.7801, -47.9292 # Default Brasilia

        sujeito = gerar_sujeito_final(
            "Ceu de Hoje", 
            agora.year, agora.month, agora.day, agora.hour, agora.minute,
            lat, lng, 
            f"Hoje: {local.cidade}", local.pais
        )
        
        chart_data = ChartDataFactory.create_natal_chart_data(sujeito)
        nome_arquivo = f"Hoje_{agora.strftime('%Y-%m-%d')}"
        
        drawer = ChartDrawer(chart_data=chart_data, chart_language="PT")
        drawer.save_svg(output_path=Path(PASTA_IMAGENS), filename=nome_arquivo)
        
        json_dados = extrair_dados_tecnicos(sujeito, chart_data)
        
        return {
            "titulo": "Posição dos Astros Hoje",
            "data": agora.strftime("%d/%m/%Y %H:%M"),
            "url_imagem": f"/imagens/{nome_arquivo}.svg",
            "planetas": json_dados["planetas"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ROTAS DE UPLOAD E LIMPEZA ---

# ROTA 4: Upload de Avatar
@app.post("/upload-avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user_id: str = Form(default="unknown"),
    type: str = Form(default="avatar")
):
    try:
        # Validar extensão
        ext = file.filename.rsplit('.', 1)[-1].lower()
        if ext not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
            raise HTTPException(status_code=400, detail="Formato não permitido. Use JPG, PNG, GIF ou WebP.")
        
        # Ler conteúdo e validar tamanho
        contents = await file.read()
        if len(contents) > 2 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Arquivo muito grande. Máximo 2MB.")
        
        # Limpar avatar antigo do usuário
        if user_id and user_id != "unknown":
            limpar_avatars_usuario(user_id)
        
        # Nome único com user_id
        filename = f"{user_id}-{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join(PASTA_AVATARS, filename)
        
        # Salvar
        with open(filepath, "wb") as f:
            f.write(contents)
        
        # URL pública
        public_url = f"https://api.vibraeu.com.br/avatars/{filename}"
        
        return {"success": True, "url": public_url, "filename": filename}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ROTA 5: Limpar dados de um usuário
@app.post("/limpar-dados")
async def limpar_dados_usuario(dados: LimpezaRequest):
    """
    Remove arquivos de um usuário.
    Tipos: "mapas", "avatars", "todos"
    """
    try:
        if not dados.user_id:
            raise HTTPException(status_code=400, detail="user_id é obrigatório")
        
        resultado = {"user_id": dados.user_id}
        
        if dados.tipo == "mapas":
            resultado["mapas_removidos"] = limpar_mapas_usuario(dados.user_id)
        elif dados.tipo == "avatars":
            resultado["avatars_removidos"] = limpar_avatars_usuario(dados.user_id)
        else:  # todos
            limpeza = limpar_tudo_usuario(dados.user_id)
            resultado.update(limpeza)
        
        resultado["success"] = True
        return resultado
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ROTA 6: Deletar avatar específico (por filename)
@app.delete("/avatar/{filename}")
async def deletar_avatar(filename: str):
    try:
        filepath = os.path.join(PASTA_AVATARS, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            return {"success": True, "message": f"Avatar {filename} removido"}
        else:
            raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def home():
    return {
        "status": "online", 
        "rotas": [
            "/natal-ll", 
            "/natal-osm", 
            "/hoje", 
            "/mapa-sinastria",
            "/upload-avatar",
            "/limpar-dados"
        ]
    }
