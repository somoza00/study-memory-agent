# Study Memory Agent

Assistente de estudos com **memória persistente entre sessões**. O usuário
descreve o que estudou, dúvidas e exercícios; o agente guarda isso no Qdrant
com embeddings semânticos e, nas sessões seguintes, recupera o contexto
relevante automaticamente.

## Stack
- **Backend**: Python 3.11+ · FastAPI · Pydantic AI v2
- **Memória**: Qdrant (self-hosted) + OpenAI `text-embedding-3-small`
- **Frontend**: React 18 + TypeScript + Vite + Tailwind CSS
- **Observabilidade**: Langfuse via OTEL nativo do Pydantic AI
- **Orquestração**: Docker Compose
- **Qualidade**: pytest · ruff · mypy (backend) · `tsc` (frontend)

## Arquitetura de memória
- `store(text, metadata)` → embedding → Qdrant
- `recall(query, limit, min_score)` → busca semântica → memórias relevantes
- Metadata por memória: `topic`, `source`, `date`, `session_id`

## Regras do projeto (ver `AGENTS.md`)
- Clean architecture: routers / services / models / core separados
- Graceful degradation: se Qdrant offline, o agente segue sem memória
- Nunca transformar endpoint síncrono se o service for async
- Conventional commits por fase

## Quickstart
```bash
cp .env.example .env        # preencha OPENAI_API_KEY
docker compose up -d --build
```
- Frontend: http://localhost:5174
- Backend API: http://localhost:8001 (health em `/health`)
- Qdrant dashboard: http://localhost:6333/dashboard
- Langfuse: http://localhost:3000

## Endpoints
| Método | Rota | Descrição |
| ------ | ---- | --------- |
| GET    | `/health` | Prontidão do backend |
| POST   | `/api/chat` | Resposta completa do agente: `{response, memories_used, session_id}` |
| POST   | `/api/chat/stream` | Resposta em Server-Sent Events (tokens + `done`) |
| GET    | `/api/memories?topic=&limit=` | Lista memórias (filtro opcional por tópico) |
| GET    | `/api/topics` | Tópicos distintos estudados |
| DELETE | `/api/memories/{id}` | Remove uma memória |

## Streaming (SSE)
`POST /api/chat/stream` com body `{"message": "...", "session_id": "..."}`
retorna `text/event-stream`:

```
data: {"type": "token", "content": "..."}
data: {"type": "done", "memories_used": N}
```

Exemplo com `curl`:
```bash
curl -N -X POST http://localhost:8001/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message": "O que é DI no FastAPI?", "session_id": "s1"}'
```

## Verificação
```bash
docker compose config -q
cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && \
  .venv/bin/ruff check app && .venv/bin/mypy app && .venv/bin/pytest
cd frontend && npm install && npm run build
```

## Status
Fases **1–4 concluídas**:
- **F1** — scaffold do monorepo + Docker Compose funcional (Qdrant, Postgres, Redis, Langfuse, backend, frontend)
- **F2** — memória core: `store`/`recall` (Qdrant + embeddings), graceful degradation
- **F3** — agente Pydantic AI (tools `store_memory`, `recall_memory`, `list_topics`) + rotas de chat e memórias
- **F4** — streaming SSE no backend + UI React/Tailwind (dark) com chat, tópicos e badge de memórias

Pendências registradas: merge do fix #3 (resposta 503 quando sem `OPENAI_API_KEY`) e filtro de tópico no `/api/chat`.