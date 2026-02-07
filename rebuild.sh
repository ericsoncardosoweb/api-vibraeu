#!/bin/bash
# Script de rebuild do backend Python
# Execute no EasyPanel após git pull

echo "🔧 Iniciando rebuild do backend..."

# Atualizar dependências
echo "📦 Instalando dependências..."
pip install --no-cache-dir -r requirements.txt

echo "✅ Backend atualizado com sucesso!"
echo "🔄 Reinicie o serviço no EasyPanel"
