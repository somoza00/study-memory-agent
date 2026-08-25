# Study Memory Agent

Assistente de estudos com **memória persistente entre sessões**. O usuário
descreve o que estudou, dúvidas e exercícios; o agente guarda isso no Qdrant
com embeddings semânticos e, nas sessões seguintes, recupera o contexto
relevante automaticamente.

## Stack
- **Backend**: Python 3.11+ · FastAPI · Pydantic AI v2
- **Memória**: Qdrant (self-hosted) + OpenAI `text-embedding-3-small`
- **Frontend**: React + TypeScript + Vite
- **Observabilidade**: Langfuse
- **Orquestração**: Docker Compose
- **Qualidade**: pytest · ruff · mypy

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

## Verificação
```bash
docker compose config -q
cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest
cd frontend && npm install && npm run build
```

## Status
Scaffold inicial (estrutura + compose funcional). Lógica por implementar nas
fases seguintes (store/recall, agente, rotas, UI).
