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
- **Qualidade**: pytest · ruff · mypy (backend) · `tsc` + Vitest (frontend)

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

> **Langfuse (observabilidade) é opcional e opt-in.** O `docker compose up` sobe só
> `qdrant` + `backend` + `frontend`. Para o tracing, suba
> `docker compose --profile observability up -d` (adiciona `postgres`, `redis` e
> `langfuse` em http://localhost:3000) **e** ligue `LANGFUSE_ENABLED=true` — sem
> isso o backend não exporta nada (e é de propósito: com o Langfuse fora do ar, o
> exporter falhava a cada span e enchia o log de "Failed to export span batch").
>
> A imagem do Langfuse está fixada em **v2** de propósito: o v3 exige ClickHouse,
> armazenamento S3-compatível e um container `worker` (o Postgres guarda só
> metadados e o Redis a fila). Para migrar ao v3, adicione esses serviços e defina
> `CLICKHOUSE_URL`/`CLICKHOUSE_USER`/`CLICKHOUSE_PASSWORD` + `LANGFUSE_S3_*`.
>
> **Atenção ao ligar o tracing:** o exporter que o agente usa é OTLP, e o endpoint
> OTLP (`/api/public/otel/v1/traces`) **só existe no Langfuse v3** — contra a v2 ele
> responde 404. Ou seja: com a stack v2 (a daqui) o profile sobe e a UI funciona,
> mas `LANGFUSE_ENABLED=true` não vai entregar traces; para tracing de verdade
> suba o v3.

## Recall (busca de memória)
`RECALL_LIMIT` (default 5), `RECALL_MIN_SCORE` e `RECALL_SCOPE` controlam o que o
chat recupera.

`RECALL_MIN_SCORE` vazio usa um default por provedor de embedding: **0.7** com
`EMBEDDING_PROVIDER=openai` e **0.55** com `EMBEDDING_PROVIDER=local`, porque o
modelo local produz scores sistematicamente mais baixos — medido: consulta não
relacionada ≤ 0.19 e memória relevante entre 0.62 e 0.89. Com o corte único de 0.7
(calibrado para a OpenAI) o agente respondia sem contexto em parte das perguntas
mesmo tendo a memória gravada.

`RECALL_SCOPE` (default `all`) define **de quais sessões** as memórias entram no
contexto: `all` busca em todas as conversas; `session` restringe à conversa atual.
O default é `all` porque o frontend cria uma sessão nova a cada carregamento de
página — com `session`, o agente chegava a cada conversa sem saber de nada do que
você já tinha estudado (o oposto da proposta do projeto).

## Provedores (agente e embeddings)
O agente (chat) fala com qualquer endpoint OpenAI-compatível via
`OPENAI_BASE_URL` — OpenCode Zen/Go, Ollama, vLLM, LiteLLM etc. Provedores que
exigem headers próprios usam `OPENAI_EXTRA_HEADERS` (JSON): o OpenCode Go pede
um `x-opencode-session` estável.

Os **embeddings têm provedor próprio** (`EMBEDDING_PROVIDER`), porque nem todo
provedor de chat serve `/embeddings` — o OpenCode, por exemplo, expõe só
`/chat/completions` (a rota de embeddings responde 404):

- `openai` (default): endpoint OpenAI-compatível, com `EMBEDDING_BASE_URL` /
  `EMBEDDING_API_KEY` (vazias = herdam as do agente).
- `local`: ONNX no próprio processo via `fastembed` (extra
  `local-embeddings`), sem chave e sem rede depois do primeiro download dos
  pesos. Multilíngue, roda offline.

Exemplo — agente no OpenCode Go, embeddings locais (sem chave da OpenAI):
```bash
OPENAI_BASE_URL=https://opencode.ai/zen/go/v1
OPENAI_API_KEY=<chave do OpenCode>
AGENT_MODEL=deepseek-v4.1-flash
OPENAI_EXTRA_HEADERS={"x-opencode-session":"study-memory-agent","User-Agent":"study-memory-agent/1.0"}
EMBEDDING_PROVIDER=local
EMBEDDING_DIM=384
```

> **Trocar de modelo de embedding exige recriar a collection.** `EMBEDDING_DIM`
> precisa casar com o modelo (OpenAI `text-embedding-3-small` = 1536; MiniLM
> multilíngue = 384) e a collection do Qdrant guarda a dimensão da criação —
> vetores de outro tamanho são rejeitados. Para trocar, recrie a collection
> (`docker compose down -v`, ou apague só a collection
> `study_memories` no dashboard em http://localhost:6333/dashboard). O backend
> falha com mensagem explícita quando `EMBEDDING_DIM` e o modelo divergem.

## Endpoints
| Método | Rota | Descrição |
| ------ | ---- | --------- |
| GET    | `/health` | Prontidão do backend |
| POST   | `/api/chat` | Resposta completa do agente: `{response, memories_used, session_id}` |
| POST   | `/api/chat/stream` | Resposta em Server-Sent Events (tokens + `done`) |
| GET    | `/api/memories?topic=&limit=` | Lista memórias (filtro opcional por tópico) |
| GET    | `/api/topics` | Tópicos distintos estudados |
| PATCH  | `/api/topics` | Renomeia um tópico (e todas as memórias dele): `{topic, name}` |
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
cd frontend && npm ci && npm run build && npm test
```

> **Atalhos (Makefile):** `make config` (valida o compose), `make venv` (cria o `.venv` do backend), `make lint` (ruff+mypy), `make test` (ruff+mypy+pytest) e `make frontend-build` (npm ci + build).

## Status
Fases **1–4 concluídas**:
- **F1** — scaffold do monorepo + Docker Compose funcional (Qdrant, Postgres, Redis, Langfuse, backend, frontend)
- **F2** — memória core: `store`/`recall` (Qdrant + embeddings), graceful degradation
- **F3** — agente Pydantic AI (tools `store_memory`, `recall_memory`, `list_topics`) + rotas de chat e memórias
- **F4** — streaming SSE no backend + UI React/Tailwind (dark) com chat, tópicos e badge de memórias

Pendências: **filtro de tópico no `/api/chat`**. O antigo fix #3 (resposta 503
quando sem `OPENAI_API_KEY`) **não será mergeado**: o tratamento de erro do
provider já foi coberto depois (o endpoint não-stream responde erro estruturado
quando o provider falha) — mantê-lo conflitaria com o comportamento atual.

**Robustez/ops aplicados depois das fases iniciais:** auth `X-API-Key`
(fail-closed em produção), redação de segredos no logging, frontend rodando
como usuário `node` (non-root), healthchecks de backend **e** frontend,
`restart: unless-stopped`, `.editorconfig`, `.gitattributes`, Dependabot
(pip/npm/docker/actions) e `Makefile` com os gates do CI.