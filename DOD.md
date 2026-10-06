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
- [x] Sem `500` cru nos endpoints de chat/memória (502/503 estruturados).

🟡 **Importante**
- [x] `OPENAI_BASE_URL` configurável (agente + embeddings) — roda em endpoint
      OpenAI-compatível (Ollama/vLLM/LiteLLM), não só na OpenAI.
- [x] `VectorStore` self-heal (recria a collection após wipe/falha).
- [x] Cobertura de testes de frontend (Vitest + Testing Library; `npm test`).
- [x] Stack Langfuse (postgres/redis/langfuse) atrás do profile `observability`
      do compose — `docker compose up` sobe só qdrant+backend+frontend.

🟢 **Nice-to-have**
- [ ] Autenticação de usuário / multi-tenant (hoje `X-API-Key` compartilhada).
- [ ] Paginação (`offset`) na listagem de memórias; edição de memória (PATCH).
