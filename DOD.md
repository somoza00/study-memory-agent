# Definition of Done — study-memory-agent

> Referência apenas: define quando uma mudança/feature/release está PRONTA.
> Gate canônico: `make test` (backend) e o build do frontend (`tsc && vite build`).

## 1. Escopo
Assistente de estudos com memória persistente (Qdrant + embeddings), agente
Pydantic AI, SSE e observabilidade Langfuse.

## 2. DoD por mudança (todo PR)
- [ ] `make test` verde: `ruff check app` + `mypy app` + `pytest` (dentro de
      `backend/`).
- [ ] Mudança no frontend: `npm run build` (`tsc && vite build`) verde.
- [ ] **Graceful degradation** preservado: Qdrant/OpenAI/LLM fora NÃO vira `500`
      — degrada (lista vazia, `persisted=False`, 502/503 estruturado) e o
      desfecho é exposto, não mascarado.
- [ ] Router fino: rota delega ao service (sem lógica de negócio no router).
- [ ] Contrato de metadata por memória mantido (`topic`, `source`, `date`,
      `session_id`); campos novos em `.env.example` (sem duplicata).
- [ ] Mudança de infra → `docker compose config -q` antes do commit.
- [ ] Commit convencional + PR revisado.

## 3. DoD por feature (incremento)
- [ ] Endpoint com `response_model`; `topic`/`session_id` propagados quando couber.
- [ ] Testes cobrindo o novo comportamento e a degradação associada.
- [ ] README/endpoints atualizados.

## 4. DoD de release (produção)
🔴 **Blocking**
- [x] `/api/health` reporta o Qdrant (`degraded` se fora) sem 500.
- [x] `API_KEY` obrigatória em produção (fail-closed no `Settings`).
- [x] Sem `500` cru nos endpoints de chat/memória (502/503 estruturados) —
      inclui o caso "provedor do LLM não configurado": o agente guarda a falha de
      inicialização e o chat responde **503** com o motivo, em vez do 500 que
      subia da resolução da dependência do FastAPI.

🟡 **Importante**
- [x] `OPENAI_BASE_URL` + `OPENAI_EXTRA_HEADERS` (agente) e
      `EMBEDDING_PROVIDER`/`EMBEDDING_BASE_URL`/`EMBEDDING_DIM` (embeddings) —
      roda em endpoint OpenAI-compatível (OpenCode/Ollama/vLLM/LiteLLM) e com
      embeddings locais (ONNX), sem depender da OpenAI.
- [x] `VectorStore` self-heal (recria a collection após wipe/falha).
- [x] Cobertura de testes de frontend (Vitest + Testing Library; `npm test`).
- [x] Stack Langfuse (postgres/redis/langfuse) atrás do profile `observability`
      do compose — `docker compose up` sobe só qdrant+backend+frontend. A imagem
      está fixada na **v2** (o v3 exige ClickHouse + S3 + worker) e o profile
      sobe de fato (verificado: `langfuse 2.95.11`, `/api/public/health` OK).
      Limite conhecido: a exportação OTLP do agente só existe no v3 — com a v2,
      `LANGFUSE_ENABLED=true` não entrega traces (endpoint responde 404).
- [x] Recall configurável e coerente: `RECALL_MIN_SCORE` (default por provedor
      de embedding: 0.7 OpenAI / 0.55 local) e `RECALL_SCOPE` (default `all`) —
      antes o corte era 0.7 fixo e o recall filtrava pela sessão atual, o que
      fazia o agente esquecer tudo entre conversas.
- [x] Grafia canônica de tópico: "FastAPI" e "fastapi" não viram dois tópicos.
- [x] Cliente do Qdrant alinhado ao servidor do compose (`qdrant-client<1.13`).
- [x] Frontend: sidebar tenta de novo quando o backend ainda está subindo e
      explica a lista vazia em vez de ficar em branco sem motivo.

🟢 **Nice-to-have**
- [ ] Autenticação de usuário / multi-tenant (hoje `X-API-Key` compartilhada).
- [ ] Paginação (`offset`) na listagem de memórias; edição de memória (PATCH).
- [ ] Seletor de modelo na UI (o provedor expõe a lista em `/v1/models`; o
      Pydantic AI aceita override por execução via `agent.run(model=...)`).
