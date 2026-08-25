# study-memory-backend

Backend do Study Memory Agent — FastAPI + Pydantic AI + Qdrant + Langfuse.

- Documentação e quickstart: ler [`../README.md`](../README.md)
- Convenções do repo: ver [`../AGENTS.md`](../AGENTS.md)

## Estrutura
- `app/api/` → routers HTTP (thin)
- `app/services/` → lógica de negócio (store/recall, embeddings, agente)
- `app/models/` → schemas Pydantic + contratos de domínio
- `app/core/` → config, logging

## Desenvolvimento
```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check app
.venv/bin/mypy app
.venv/bin/pytest
```