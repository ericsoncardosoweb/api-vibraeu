# VibraEU API

> API unificada para a plataforma Vibra Eu — Astrologia + AIMS + Uploads

**Endpoint:** `https://api.vibraeu.com.br`

## Rotas

### Astrologia (Produção)
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/natal-ll` | Mapa natal por lat/long |
| POST | `/natal-osm` | Mapa natal por cidade (geocoding) |
| POST | `/hoje` | Mapa do céu atual |
| POST | `/upload-avatar` | Upload de avatar (Pillow + Bunny CDN) |
| POST | `/limpar-dados` | Limpar dados do usuário |
| DELETE | `/avatar/{filename}` | Deletar avatar específico |

### AIMS (Interpretações Avançadas)
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/admin/trigger-event` | Disparar evento AIMS |
| POST | `/admin/process-queue` | Processar fila manualmente |
| GET | `/admin/templates` | Listar templates |
| POST | `/trigger` | Trigger de interpretação |
| POST | `/process/now` | Processar imediatamente |
| GET | `/scheduler/status` | Status do agendador |

### Sistema
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health` | Health check |
| GET | `/health/detailed` | Health check detalhado |
| GET | `/docs` | Swagger UI |
| GET | `/` | Info da API |

## Segurança

Todas as rotas (exceto `/health`, `/docs`, `/`) são protegidas via header `X-API-Key`.

```bash
# Exemplo de requisição autenticada
curl -X POST https://api.vibraeu.com.br/natal-ll \
  -H "X-API-Key: SUA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"nome": "Teste", "ano": 1990, ...}'
```

## Como rodar

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Deploy (Docker)

```bash
docker build -t vibraeu-api .
docker run -p 80:80 --env-file .env vibraeu-api
```
