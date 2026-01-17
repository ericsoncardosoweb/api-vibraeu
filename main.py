from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
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
import httpx

# --- BUNNY CDN CONFIGURATION ---
BUNNY_STORAGE_ZONE = os.getenv("BUNNY_STORAGE_ZONE", "vibraeu-storage")
BUNNY_STORAGE_API_KEY = os.getenv("BUNNY_STORAGE_API_KEY", "f12a564e-13de-42ea-acd4aa5863a8-2806-44eb")
BUNNY_STORAGE_HOSTNAME = os.getenv("BUNNY_STORAGE_HOSTNAME", "br.storage.bunnycdn.com")
BUNNY_CDN_URL = os.getenv("BUNNY_CDN_URL", "https://vibraeu.b-cdn.net")
BUNNY_ENABLED = os.getenv("BUNNY_ENABLED", "true").lower() == "true"

app = FastAPI(title="API Astrologia VibraEu - Multi Rotas")

# --- CORS MIDDLEWARE ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permitir todas as origens
    allow_credentials=True,
    allow_methods=["*"],  # Permitir todos os métodos
    allow_headers=["*"],  # Permitir todos os headers
)

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

# --- BUNNY CDN UPLOAD FUNCTION ---
async def upload_to_bunny(file_content: bytes, filename: str, path: str = "avatars") -> dict:
    """
    Upload a file to Bunny CDN Storage.
    Returns dict with success status and CDN URL.
    """
    try:
        full_path = f"{path}/{filename}" if path else filename
        url = f"https://{BUNNY_STORAGE_HOSTNAME}/{BUNNY_STORAGE_ZONE}/{full_path}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.put(
                url,
                content=file_content,
                headers={
                    "AccessKey": BUNNY_STORAGE_API_KEY,
                    "Content-Type": "application/octet-stream",
                }
            )
            response.raise_for_status()
        
        cdn_url = f"{BUNNY_CDN_URL}/{full_path}"
        print(f"[Bunny CDN] Upload success: {cdn_url}")
        return {"success": True, "cdn_url": cdn_url}
    except Exception as e:
        print(f"[Bunny CDN] Upload failed: {e}")
        return {"success": False, "error": str(e)}

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
        from io import StringIO
        
        sujeito = gerar_sujeito_final(
            dados.nome, dados.ano, dados.mes, dados.dia, dados.hora, dados.minuto,
            dados.latitude, dados.longitude, dados.cidade_label, dados.pais_label
        )
        
        chart_data = ChartDataFactory.create_natal_chart_data(sujeito)
        
        # Nome do arquivo
        nome_seguro = dados.nome.replace(' ', '_')
        if dados.user_id:
            # Limpar mapa antigo do usuário antes de criar novo (local)
            limpar_arquivos_usuario(PASTA_IMAGENS, dados.user_id, "Natal_LL_")
            nome_arquivo = f"Natal_LL_{nome_seguro}_{dados.user_id}.svg"
        else:
            nome_arquivo = f"Natal_LL_{nome_seguro}_{uuid.uuid4().hex[:8]}.svg"
        
        # Gerar SVG em memória
        drawer = ChartDrawer(chart_data=chart_data, chart_language="PT")
        svg_string = drawer.makeTemplate()
        svg_bytes = svg_string.encode('utf-8')
        
        # ESTRATÉGIA: Tentar Bunny CDN primeiro, fallback para local
        public_url = None
        storage_type = "local"
        
        if BUNNY_ENABLED:
            bunny_result = await upload_to_bunny(svg_bytes, nome_arquivo, "mapas")
            if bunny_result["success"]:
                public_url = bunny_result["cdn_url"]
                storage_type = "bunny_cdn"
                print(f"[Upload] Mapa salvo no Bunny CDN: {public_url}")
        
        # Fallback para local se Bunny falhou ou está desabilitado
        if not public_url:
            filepath = os.path.join(PASTA_IMAGENS, nome_arquivo)
            with open(filepath, "wb") as f:
                f.write(svg_bytes)
            public_url = f"https://api.vibraeu.com.br/imagens/{nome_arquivo}"
            storage_type = "local"
            print(f"[Upload] Mapa salvo localmente: {public_url}")
        
        json_dados = extrair_dados_tecnicos(sujeito, chart_data)
        
        return {
            "tipo": "Natal (Lat/Long)",
            "url_imagem": public_url,
            "storage": storage_type,
            "dados": json_dados
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ROTA 2: Busca por Nome (OSM)
@app.post("/natal-osm")
async def natal_busca_cidade(dados: PessoaOSM):
    try:
        from io import StringIO
        
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
        
        # Nome do arquivo
        nome_seguro = dados.nome.replace(' ', '_')
        if dados.user_id:
            # Limpar mapa antigo do usuário antes de criar novo (local)
            limpar_arquivos_usuario(PASTA_IMAGENS, dados.user_id, "Natal_OSM_")
            nome_arquivo = f"Natal_OSM_{nome_seguro}_{dados.user_id}.svg"
        else:
            nome_arquivo = f"Natal_OSM_{nome_seguro}_{uuid.uuid4().hex[:8]}.svg"
        
        # Gerar SVG em memória
        drawer = ChartDrawer(chart_data=chart_data, chart_language="PT")
        svg_string = drawer.makeTemplate()
        svg_bytes = svg_string.encode('utf-8')
        
        # ESTRATÉGIA: Tentar Bunny CDN primeiro, fallback para local
        public_url = None
        storage_type = "local"
        
        if BUNNY_ENABLED:
            bunny_result = await upload_to_bunny(svg_bytes, nome_arquivo, "mapas")
            if bunny_result["success"]:
                public_url = bunny_result["cdn_url"]
                storage_type = "bunny_cdn"
                print(f"[Upload] Mapa salvo no Bunny CDN: {public_url}")
        
        # Fallback para local se Bunny falhou ou está desabilitado
        if not public_url:
            filepath = os.path.join(PASTA_IMAGENS, nome_arquivo)
            with open(filepath, "wb") as f:
                f.write(svg_bytes)
            public_url = f"https://api.vibraeu.com.br/imagens/{nome_arquivo}"
            storage_type = "local"
            print(f"[Upload] Mapa salvo localmente: {public_url}")
        
        json_dados = extrair_dados_tecnicos(sujeito, chart_data)

        return {
            "tipo": "Natal (Busca Nome)",
            "local_encontrado": loc.address if loc else "Default",
            "coords": {"lat": lat, "lng": lng},
            "url_imagem": public_url,
            "storage": storage_type,
            "dados": json_dados
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ROTA 3: Céu de Hoje
@app.post("/hoje")
async def ceu_de_hoje(local: LocalizacaoHoje):
    try:
        from io import StringIO
        
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
        nome_arquivo = f"Hoje_{agora.strftime('%Y-%m-%d_%H-%M')}.svg"
        
        # Gerar SVG em memória
        drawer = ChartDrawer(chart_data=chart_data, chart_language="PT")
        svg_string = drawer.makeTemplate()
        svg_bytes = svg_string.encode('utf-8')
        
        # ESTRATÉGIA: Tentar Bunny CDN primeiro, fallback para local
        public_url = None
        storage_type = "local"
        
        if BUNNY_ENABLED:
            bunny_result = await upload_to_bunny(svg_bytes, nome_arquivo, "mapas")
            if bunny_result["success"]:
                public_url = bunny_result["cdn_url"]
                storage_type = "bunny_cdn"
                print(f"[Upload] Mapa salvo no Bunny CDN: {public_url}")
        
        # Fallback para local se Bunny falhou ou está desabilitado
        if not public_url:
            filepath = os.path.join(PASTA_IMAGENS, nome_arquivo)
            with open(filepath, "wb") as f:
                f.write(svg_bytes)
            public_url = f"https://api.vibraeu.com.br/imagens/{nome_arquivo}"
            storage_type = "local"
            print(f"[Upload] Mapa salvo localmente: {public_url}")
        
        json_dados = extrair_dados_tecnicos(sujeito, chart_data)
        
        return {
            "titulo": "Posição dos Astros Hoje",
            "data": agora.strftime("%d/%m/%Y %H:%M"),
            "url_imagem": public_url,
            "storage": storage_type,
            "planetas": json_dados["planetas"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ROTAS DE UPLOAD E LIMPEZA ---

# ROTA 4: Upload de Avatar (com redimensionamento e compressão + Bunny CDN)
@app.post("/upload-avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user_id: str = Form(default="unknown"),
    type: str = Form(default="avatar")
):
    try:
        from PIL import Image
        from io import BytesIO
        
        # Validar extensão
        ext = file.filename.rsplit('.', 1)[-1].lower()
        if ext not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
            raise HTTPException(status_code=400, detail="Formato não permitido. Use JPG, PNG, GIF ou WebP.")
        
        # Ler conteúdo e validar tamanho (antes do processamento)
        contents = await file.read()
        if len(contents) > 5 * 1024 * 1024:  # Aumentado para 5MB antes do processamento
            raise HTTPException(status_code=400, detail="Arquivo muito grande. Máximo 5MB.")
        
        # Processar imagem com Pillow
        image = Image.open(BytesIO(contents))
        
        # Converter RGBA para RGB (necessário para JPEG)
        if image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            background.paste(image, mask=image.split()[-1] if len(image.split()) == 4 else None)
            image = background
        
        # Redimensionar para máximo 600px mantendo proporção
        max_size = 600
        if image.width > max_size or image.height > max_size:
            # Calcula nova dimensão mantendo proporção
            if image.width > image.height:
                new_width = max_size
                new_height = int((max_size / image.width) * image.height)
            else:
                new_height = max_size
                new_width = int((max_size / image.height) * image.width)
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Limpar avatar antigo do usuário (local)
        if user_id and user_id != "unknown":
            limpar_avatars_usuario(user_id)
        
        # Nome único com user_id (sempre salvar como JPEG para compressão)
        filename = f"{user_id}-{uuid.uuid4().hex[:8]}.jpg"
        
        # Converter imagem para bytes
        buffer = BytesIO()
        image.save(buffer, 'JPEG', quality=85, optimize=True)
        processed_bytes = buffer.getvalue()
        
        # ESTRATÉGIA: Tentar Bunny CDN primeiro, fallback para local
        public_url = None
        storage_type = "local"
        
        if BUNNY_ENABLED:
            bunny_result = await upload_to_bunny(processed_bytes, filename, "avatars")
            if bunny_result["success"]:
                public_url = bunny_result["cdn_url"]
                storage_type = "bunny_cdn"
                print(f"[Upload] Avatar salvo no Bunny CDN: {public_url}")
        
        # Fallback para local se Bunny falhou ou está desabilitado
        if not public_url:
            filepath = os.path.join(PASTA_AVATARS, filename)
            with open(filepath, "wb") as f:
                f.write(processed_bytes)
            public_url = f"https://api.vibraeu.com.br/avatars/{filename}"
            storage_type = "local"
            print(f"[Upload] Avatar salvo localmente: {public_url}")
        
        return {
            "success": True, 
            "url": public_url, 
            "filename": filename,
            "storage": storage_type
        }
    
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
