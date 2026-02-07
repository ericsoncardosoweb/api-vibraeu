"""
Modelos Pydantic para endpoints de astrologia.
Extraídos do main.py monolítico original.
"""

from pydantic import BaseModel
from typing import Optional


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
    user_id: Optional[str] = None  # Para identificar e limpar depois
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
    user_id: Optional[str] = None  # Para identificar e limpar depois


# 3. Modelo para Sinastria
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
