"""
Router de astrologia - Todas as rotas do monolito original preservadas.
Endpoints preservados (produção em api.vibraeu.com.br):
  - POST /natal-ll      → Mapa natal por lat/long
  - POST /natal-osm     → Mapa natal por cidade (geocoding)
  - POST /hoje           → Mapa do céu atual
  - POST /upload-avatar  → Upload de avatar com Bunny CDN
  - POST /limpar-dados   → Limpar dados do usuário
  - DELETE /avatar/{fn}  → Deletar avatar específico
"""

from fastapi import APIRouter, HTTPException, File, UploadFile, Form
from loguru import logger
import os
import uuid
from datetime import datetime
import pytz
import httpx

from models.astrology import PessoaLL, PessoaOSM, LocalizacaoHoje, LimpezaRequest
from services.astro_engine import (
    gerar_sujeito_final, extrair_dados_tecnicos, gerar_mapa_svg,
    geocode_cidade, limpar_arquivos_usuario, limpar_mapas_usuario,
    limpar_avatars_usuario, limpar_tudo_usuario, calcular_fase_lunar
)
from kerykeion.chart_data_factory import ChartDataFactory
from config import get_settings


router = APIRouter()


# --- BUNNY CDN UPLOAD (preservado do original) ---
async def upload_to_bunny(file_content: bytes, filename: str, path: str = "avatars") -> dict:
    """
    Upload a file to Bunny CDN Storage.
    Returns dict with success status and CDN URL.
    """
    settings = get_settings()
    try:
        full_path = f"{path}/{filename}" if path else filename
        url = f"https://{settings.bunny_storage_hostname}/{settings.bunny_storage_zone}/{full_path}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.put(
                url,
                content=file_content,
                headers={
                    "AccessKey": settings.bunny_storage_api_key,
                    "Content-Type": "application/octet-stream",
                }
            )
            response.raise_for_status()
        
        cdn_url = f"{settings.bunny_cdn_url}/{full_path}"
        logger.info(f"[Bunny CDN] Upload success: {cdn_url}")
        return {"success": True, "cdn_url": cdn_url}
    except Exception as e:
        logger.error(f"[Bunny CDN] Upload failed: {e}")
        return {"success": False, "error": str(e)}


# ============================================================================
# ROTA 1: Mapa Natal por Latitude/Longitude (Alta Precisão)
# ============================================================================
@router.post("/natal-ll")
async def natal_lat_long(dados: PessoaLL):
    settings = get_settings()
    try:
        sujeito = gerar_sujeito_final(
            dados.nome, dados.ano, dados.mes, dados.dia, dados.hora, dados.minuto,
            dados.latitude, dados.longitude, dados.cidade_label, dados.pais_label
        )
        
        chart_data = ChartDataFactory.create_natal_chart_data(sujeito)
        
        # Nome do arquivo
        nome_seguro = dados.nome.replace(' ', '_')
        if dados.user_id:
            # Limpar mapa antigo do usuário antes de criar novo (local)
            limpar_arquivos_usuario(settings.pasta_imagens, dados.user_id, "Natal_LL_")
            nome_arquivo_base = f"Natal_LL_{nome_seguro}_{dados.user_id}"
        else:
            nome_arquivo_base = f"Natal_LL_{nome_seguro}_{uuid.uuid4().hex[:8]}"
        
        # 1. Salvar SVG localmente
        logger.debug(f"Salvando mapa localmente: {nome_arquivo_base}")
        filepath_local = gerar_mapa_svg(chart_data, settings.pasta_imagens, nome_arquivo_base)
        nome_arquivo_completo = f"{nome_arquivo_base}.svg"
        logger.debug(f"Mapa salvo com sucesso")
        
        # 2. Ler o arquivo salvo
        try:
            with open(filepath_local, "rb") as f:
                svg_bytes = f.read()
            logger.debug(f"Arquivo lido: {len(svg_bytes)} bytes")
        except Exception as e:
            logger.error(f"Falha ao ler arquivo local: {e}")
            raise HTTPException(status_code=500, detail=f"Erro ao ler arquivo gerado: {e}")
        
        # 3. Tentar enviar para Bunny CDN
        public_url = None
        storage_type = "local"
        
        if settings.bunny_enabled:
            logger.debug("Tentando upload para Bunny CDN...")
            bunny_result = await upload_to_bunny(svg_bytes, nome_arquivo_completo, "mapas")
            if bunny_result["success"]:
                public_url = bunny_result["cdn_url"]
                storage_type = "bunny_cdn"
                logger.info(f"[Upload] ✅ Mapa salvo no Bunny CDN: {public_url}")
        
        # 4. Fallback para local se Bunny falhou
        if not public_url:
            public_url = f"{settings.api_base_url}/imagens/{nome_arquivo_completo}"
            storage_type = "local"
            logger.info(f"[Upload] 📁 Mapa mantido localmente: {public_url}")
        
        json_dados = extrair_dados_tecnicos(sujeito, chart_data)
        
        return {
            "tipo": "Natal (Lat/Long)",
            "url_imagem": public_url,
            "storage": storage_type,
            "dados": json_dados
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro geral: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ROTA 2: Mapa Natal por Nome da Cidade (OpenStreetMap)
# ============================================================================
@router.post("/natal-osm")
async def natal_busca_cidade(dados: PessoaOSM):
    settings = get_settings()
    try:
        lat, lng, cidade_display, address = geocode_cidade(dados.cidade, dados.estado, dados.pais)

        sujeito = gerar_sujeito_final(
            dados.nome, dados.ano, dados.mes, dados.dia, dados.hora, dados.minuto,
            lat, lng, cidade_display, dados.pais
        )
        
        chart_data = ChartDataFactory.create_natal_chart_data(sujeito)
        
        # Nome do arquivo
        nome_seguro = dados.nome.replace(' ', '_')
        if dados.user_id:
            limpar_arquivos_usuario(settings.pasta_imagens, dados.user_id, "Natal_OSM_")
            nome_arquivo_base = f"Natal_OSM_{nome_seguro}_{dados.user_id}"
        else:
            nome_arquivo_base = f"Natal_OSM_{nome_seguro}_{uuid.uuid4().hex[:8]}"
        
        # 1. Salvar SVG
        filepath_local = gerar_mapa_svg(chart_data, settings.pasta_imagens, nome_arquivo_base)
        nome_arquivo_completo = f"{nome_arquivo_base}.svg"
        
        # 2. Ler arquivo
        with open(filepath_local, "rb") as f:
            svg_bytes = f.read()
        
        # 3. Bunny CDN
        public_url = None
        storage_type = "local"
        
        if settings.bunny_enabled:
            bunny_result = await upload_to_bunny(svg_bytes, nome_arquivo_completo, "mapas")
            if bunny_result["success"]:
                public_url = bunny_result["cdn_url"]
                storage_type = "bunny_cdn"
                logger.info(f"[Upload] Mapa salvo no Bunny CDN: {public_url}")
        
        # 4. Fallback
        if not public_url:
            public_url = f"{settings.api_base_url}/imagens/{nome_arquivo_completo}"
            storage_type = "local"
            logger.info(f"[Upload] Mapa mantido localmente: {public_url}")
        
        json_dados = extrair_dados_tecnicos(sujeito, chart_data)

        return {
            "tipo": "Natal (Busca Nome)",
            "local_encontrado": address or "Default",
            "coords": {"lat": lat, "lng": lng},
            "url_imagem": public_url,
            "storage": storage_type,
            "dados": json_dados
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ROTA 3: Céu de Hoje
# ============================================================================
@router.post("/hoje")
async def ceu_de_hoje(local: LocalizacaoHoje):
    settings = get_settings()
    try:
        # Pega hora atual de SP
        fuso = pytz.timezone("America/Sao_Paulo")
        agora = datetime.now(fuso)
        
        # Busca coords da referência
        lat, lng, _, _ = geocode_cidade(local.cidade, local.estado, local.pais)

        sujeito = gerar_sujeito_final(
            "Ceu de Hoje", 
            agora.year, agora.month, agora.day, agora.hour, agora.minute,
            lat, lng, 
            f"Hoje: {local.cidade}", local.pais
        )
        
        chart_data = ChartDataFactory.create_natal_chart_data(sujeito)
        nome_arquivo_base = f"Hoje_{agora.strftime('%Y-%m-%d_%H-%M')}"
        
        # 1. Salvar SVG
        filepath_local = gerar_mapa_svg(chart_data, settings.pasta_imagens, nome_arquivo_base)
        nome_arquivo_completo = f"{nome_arquivo_base}.svg"
        
        # 2. Ler arquivo
        with open(filepath_local, "rb") as f:
            svg_bytes = f.read()
        
        # 3. Bunny CDN
        public_url = None
        storage_type = "local"
        
        if settings.bunny_enabled:
            bunny_result = await upload_to_bunny(svg_bytes, nome_arquivo_completo, "mapas")
            if bunny_result["success"]:
                public_url = bunny_result["cdn_url"]
                storage_type = "bunny_cdn"
                logger.info(f"[Upload] Mapa salvo no Bunny CDN: {public_url}")
        
        # 4. Fallback
        if not public_url:
            public_url = f"{settings.api_base_url}/imagens/{nome_arquivo_completo}"
            storage_type = "local"
            logger.info(f"[Upload] Mapa mantido localmente: {public_url}")
        
        json_dados = extrair_dados_tecnicos(sujeito, chart_data)
        
        # Calcular fase lunar real usando posições Sol/Lua
        fase_lua = calcular_fase_lunar(sujeito)
        
        return {
            "titulo": "Posição dos Astros Hoje",
            "data": agora.strftime("%d/%m/%Y %H:%M"),
            "fase_lua": fase_lua,
            "url_imagem": public_url,
            "storage": storage_type,
            "planetas": json_dados["planetas"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ROTA 4: Upload de Avatar (com Pillow resize + Bunny CDN + fallback local)
# ============================================================================
@router.post("/upload-avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user_id: str = Form(default="unknown"),
    type: str = Form(default="avatar")
):
    settings = get_settings()
    try:
        from PIL import Image
        from io import BytesIO
        
        # Validar extensão
        ext = file.filename.rsplit('.', 1)[-1].lower()
        if ext not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
            raise HTTPException(status_code=400, detail="Formato não permitido. Use JPG, PNG, GIF ou WebP.")
        
        # Ler conteúdo e validar tamanho (antes do processamento)
        contents = await file.read()
        if len(contents) > 5 * 1024 * 1024:  # 5MB
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
            if image.width > image.height:
                new_width = max_size
                new_height = int((max_size / image.width) * image.height)
            else:
                new_height = max_size
                new_width = int((max_size / image.height) * image.width)
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Limpar avatar antigo do usuário (local)
        if user_id and user_id != "unknown":
            limpar_avatars_usuario(settings.pasta_avatars, user_id)
        
        # Nome único com user_id (sempre salvar como JPEG para compressão)
        filename = f"{user_id}-{uuid.uuid4().hex[:8]}.jpg"
        
        # Converter imagem para bytes
        buffer = BytesIO()
        image.save(buffer, 'JPEG', quality=85, optimize=True)
        processed_bytes = buffer.getvalue()
        
        # ESTRATÉGIA: Tentar Bunny CDN primeiro, fallback para local
        public_url = None
        storage_type = "local"
        
        if settings.bunny_enabled:
            bunny_result = await upload_to_bunny(processed_bytes, filename, "avatars")
            if bunny_result["success"]:
                public_url = bunny_result["cdn_url"]
                storage_type = "bunny_cdn"
                logger.info(f"[Upload] Avatar salvo no Bunny CDN: {public_url}")
        
        # Fallback para local se Bunny falhou ou está desabilitado
        if not public_url:
            filepath = os.path.join(settings.pasta_avatars, filename)
            with open(filepath, "wb") as f:
                f.write(processed_bytes)
            public_url = f"{settings.api_base_url}/avatars/{filename}"
            storage_type = "local"
            logger.info(f"[Upload] Avatar salvo localmente: {public_url}")
        
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


# ============================================================================
# ROTA 5: Limpar dados de um usuário
# ============================================================================
@router.post("/limpar-dados")
async def limpar_dados_usuario_route(dados: LimpezaRequest):
    """
    Remove arquivos de um usuário.
    Tipos: "mapas", "avatars", "todos"
    """
    settings = get_settings()
    try:
        if not dados.user_id:
            raise HTTPException(status_code=400, detail="user_id é obrigatório")
        
        resultado = {"user_id": dados.user_id}
        
        if dados.tipo == "mapas":
            resultado["mapas_removidos"] = limpar_mapas_usuario(settings.pasta_imagens, dados.user_id)
        elif dados.tipo == "avatars":
            resultado["avatars_removidos"] = limpar_avatars_usuario(settings.pasta_avatars, dados.user_id)
        else:  # todos
            limpeza = limpar_tudo_usuario(settings.pasta_imagens, settings.pasta_avatars, dados.user_id)
            resultado.update(limpeza)
        
        resultado["success"] = True
        return resultado
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ROTA 6: Deletar avatar específico (por filename)
# ============================================================================
@router.delete("/avatar/{filename}")
async def deletar_avatar(filename: str):
    settings = get_settings()
    try:
        filepath = os.path.join(settings.pasta_avatars, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            return {"success": True, "message": f"Avatar {filename} removido"}
        else:
            raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
