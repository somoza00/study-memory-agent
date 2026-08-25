# AGENTS.md — Study Memory Agent

Convenções que todo agente de codificação deve seguir neste repo.

## Arquitetura
- **Clean architecture** em `backend/app`:
  - `api/` → routers HTTP (thin, só parse/response)
  - `services/` → lógica de negócio (orquestra memory/embedding/agent)
  - `models/` → schemas Pydantic + contratos de domínio
  - `core/` → config, logging, infraestrutura transversal
- Rotas não contêm lógica; delegam ao service.

## Contrato de memória
- `store(text, metadata)` → embedding → Qdrant
- `recall(query, limit, min_score)` → busca semântica → memórias
- Metadata obrigatória por memória: `topic`, `source`, `date`, `session_id`

## Regras
- **Graceful degradation**: Qdrant offline ⇒ agente responde sem memória (nunca 500).
- **Nunca** colocar `async def` no router e rodar service síncrono (bloqueia event loop).
  Service async ⇒ endpoint async; use `run_in_executor` só se inevitável.
- **Conventional commits** por fase: `feat:`, `fix:`, `chore:`, `refactor:`, `docs:`.
- **Nunca commit na main**: criar branch `feat/<fase>` primeiro.
- **Env discipline**: toda variável nova entra no `.env.example` (sem duplicata).

## Verificação por fase
- `cd backend && .venv/bin/ruff check app && .venv/bin/mypy app && .venv/bin/pytest`
- `docker compose config -q` antes de qualquer mudança de infra.
