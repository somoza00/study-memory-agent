"""Testes dos routers de chat e memórias com dependências mockadas.

O agente Pydantic AI e o MemoryService são substituídos por `AsyncMock`
via `app.dependency_overrides` — não se testa o LLM, só o roteamento.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.deps import get_agent_service, get_memory_service, get_vector_store
from app.main import app
from app.models.memory import MemoryMetadata, StoredMemory
from app.services.agent_service import AgentService, AgentTimeoutError, ChatResult, StreamEvent
from app.services.memory_service import RenameTopicResult, RenameTopicStatus

# Id de memória usado nos testes de rota: a API só aceita UUID (422 para o
# resto) — os ids vêm do Qdrant, que sempre gera UUID.
_MEMORY_ID = "6f1f4c2e-0000-4000-8000-000000000001"


class _FakeStreamAgent:
    """Substituto do AgentService que emite eventos SSE sem tocar o LLM."""

    async def stream_chat(
        self,
        message: str,
        session_id: str,
        topic: str | None = None,
        *,
        model: str | None = None,
    ):
        del message, session_id, topic, model
        yield StreamEvent(type="token", content="Olá")
        yield StreamEvent(type="token", content=" mundo")
        yield StreamEvent(type="done", memories_used=2)


def _agent_mock() -> AsyncMock:
    agent = AsyncMock()
    agent.chat.return_value = ChatResult(response="Resposta simulada do agente.", memories_used=2)
    return agent


def _memory_mock() -> AsyncMock:
    metadata = MemoryMetadata(
        topic="fastapi", source="livro", date=date(2026, 8, 25), session_id="s1"
    )
    memory = AsyncMock()
    memory.list.return_value = ([StoredMemory(id="abc", text="texto", metadata=metadata)], None)
    memory.list_topics.return_value = ["fastapi", "react"]
    memory.list_sessions.return_value = ["s1", "s2"]
    memory.count.return_value = 1
    memory.delete.return_value = True
    memory.delete_session.return_value = True
    # Default neutro: devolve o tópico apenas normalizado (testes específicos de
    # grafia canônica sobrescrevem com o valor existente).
    memory.canonical_topic.side_effect = lambda topic: topic.strip()
    memory.rename_topic.return_value = RenameTopicResult(
        status=RenameTopicStatus.RENAMED, updated=2
    )
    return memory


def test_chat_returns_response_and_memories_used() -> None:
    agent = _agent_mock()
    app.dependency_overrides[get_agent_service] = lambda: agent
    try:
        client = TestClient(app)
        resp = client.post("/api/chat", json={"message": "oi", "session_id": "s1"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["response"] == "Resposta simulada do agente."
        assert body["memories_used"] == 2
        assert body["session_id"] == "s1"
        agent.chat.assert_awaited_once_with("oi", "s1", None, model=None)
    finally:
        app.dependency_overrides.clear()


def test_chat_rejects_oversized_message() -> None:
    """Mensagem acima do limite é rejeitada na validação (422)."""
    app.dependency_overrides[get_agent_service] = lambda: AsyncMock()
    try:
        client = TestClient(app)
        resp = client.post("/api/chat", json={"message": "x" * 10_001, "session_id": "s1"})
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_chat_returns_502_when_openai_fails() -> None:
    """Falha do provider no /api/chat (não-stream) vira 502, não 500 cru."""
    from openai import OpenAIError

    agent = AsyncMock()
    agent.chat.side_effect = OpenAIError("api down")
    app.dependency_overrides[get_agent_service] = lambda: agent
    try:
        client = TestClient(app)
        resp = client.post("/api/chat", json={"message": "oi", "session_id": "s1"})
        assert resp.status_code == 502
        assert "api down" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_chat_returns_502_on_non_openai_failure() -> None:
    """Erro não-OpenAI no /api/chat (não-stream) vira 502, não 500 cru (nunca 500)."""
    agent = AsyncMock()
    agent.chat.side_effect = RuntimeError("boom")
    app.dependency_overrides[get_agent_service] = lambda: agent
    try:
        client = TestClient(app)
        resp = client.post("/api/chat", json={"message": "oi", "session_id": "s1"})
        assert resp.status_code == 502
        assert "boom" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_list_memories_filters_by_topic() -> None:
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/memories?topic=fastapi&limit=5")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "abc"
        assert data[0]["metadata"]["topic"] == "fastapi"
    finally:
        app.dependency_overrides.clear()


def test_list_memories_filters_by_session() -> None:
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/memories?session_id=s1&limit=3")
        assert resp.status_code == 200, resp.text
        assert memory.list.await_args.kwargs["session_id"] == "s1"
        assert memory.list.await_args.kwargs["limit"] == 3
    finally:
        app.dependency_overrides.clear()


def test_list_memories_filters_by_source() -> None:
    """`?source=` filtra a listagem (e o total) por fonte — antes não existia."""
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/memories?source=livro")
        assert resp.status_code == 200, resp.text
        assert memory.list.await_args.kwargs["source"] == "livro"
        assert memory.count.await_args.kwargs["source"] == "livro"
    finally:
        app.dependency_overrides.clear()


def test_sessions_returns_distinct_list() -> None:
    """`GET /api/sessions` lista as sessões de conversa com memórias."""
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/sessions?limit=5")
        assert resp.status_code == 200, resp.text
        assert resp.json() == ["s1", "s2"]
        assert memory.list_sessions.await_args.kwargs["limit"] == 5
    finally:
        app.dependency_overrides.clear()


def test_topics_returns_distinct_list() -> None:
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/topics")
        assert resp.status_code == 200, resp.text
        assert resp.json() == ["fastapi", "react"]
    finally:
        app.dependency_overrides.clear()


def test_topics_forwards_limit() -> None:
    """O `limit` do GET /api/topics é repassado ao serviço (antes era ignorado)."""
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/topics?limit=10")
        assert resp.status_code == 200
        assert memory.list_topics.await_args.kwargs["limit"] == 10
    finally:
        app.dependency_overrides.clear()


def test_topic_counts_returns_counts() -> None:
    """GET /api/topics/counts devolve tópicos com a contagem real de memórias."""
    from app.models.memory import TopicCount

    memory = _memory_mock()
    memory.topic_counts.return_value = [
        TopicCount(topic="fastapi", count=3),
        TopicCount(topic="react", count=1),
    ]
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/topics/counts")
        assert resp.status_code == 200, resp.text
        assert resp.json() == [
            {"topic": "fastapi", "count": 3},
            {"topic": "react", "count": 1},
        ]
    finally:
        app.dependency_overrides.clear()


def test_search_memories_exposes_recall() -> None:
    """GET /api/memories/search expõe o recall semântico (usado pelo agente)."""
    from app.models.memory import MemoryResult

    memory = _memory_mock()
    metadata = MemoryMetadata(
        topic="fastapi", source="livro", date=date(2026, 8, 25), session_id="s1"
    )
    memory.recall.return_value = [
        MemoryResult(id="abc", text="sobre DI", score=0.9, metadata=metadata)
    ]
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get(
            "/api/memories/search", params={"q": "DI", "limit": 3, "topic": "fastapi"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body[0]["id"] == "abc"
        assert body[0]["score"] == 0.9
        memory.recall.assert_awaited_once_with("DI", 3, 0.7, "fastapi", session_id=None)
    finally:
        app.dependency_overrides.clear()


def test_search_memories_accepts_documented_limit_ceiling() -> None:
    """`?limit=50` (o `le` declarado) vale de verdade: 50 chega ao serviço, 51 é 422.

    O endpoint anunciava `le=50`, mas o serviço cortava em 20: um cliente que
    pedia 50 recebia no máximo 20 memórias sem nenhum aviso. O limite máximo
    documentado tem de ser o mesmo dos dois lados.
    """
    memory = _memory_mock()
    memory.recall.return_value = []
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/memories/search", params={"q": "DI", "limit": 50})
        assert resp.status_code == 200, resp.text
        assert memory.recall.await_args.args[1] == 50

        too_big = client.get("/api/memories/search", params={"q": "DI", "limit": 51})
        assert too_big.status_code == 422, too_big.text
    finally:
        app.dependency_overrides.clear()


def test_chat_stream_returns_sse_events() -> None:
    app.dependency_overrides[get_agent_service] = lambda: _FakeStreamAgent()
    try:
        client = TestClient(app)
        resp = client.post("/api/chat/stream", json={"message": "oi", "session_id": "s1"})
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert '"type": "token"' in resp.text
        assert '"content": "Olá' in resp.text
        assert '"type": "done"' in resp.text
        assert '"memories_used": 2' in resp.text
    finally:
        app.dependency_overrides.clear()


def test_chat_stream_emits_keepalive_while_provider_is_silent(monkeypatch) -> None:
    """Silêncio do provedor vira `: ping` (conexão viva), não um stream parado.

    Sem keep-alive o servidor não escreve NADA entre o 200 e o primeiro token;
    um proxy com timeout de conexão ociosa (nginx 60s, Cloudflare 100s) fecha o
    stream no meio e o cliente perde a resposta — o `: ping` é comentário SSE,
    ignorado pelo EventSource e pelo parser do frontend.
    """
    from app.api.routers import chat as chat_router

    class _SlowStream:
        async def stream_chat(
            self,
            message: str,
            session_id: str,
            topic: str | None = None,
            *,
            model: str | None = None,
        ):
            del message, session_id, topic, model
            await asyncio.sleep(0.2)  # provedor "pensando", nenhum token ainda
            yield StreamEvent(type="token", content="Olá")
            yield StreamEvent(type="done", memories_used=1)

    monkeypatch.setattr(chat_router, "_SSE_KEEPALIVE_SECONDS", 0.05)
    app.dependency_overrides[get_agent_service] = lambda: _SlowStream()
    try:
        client = TestClient(app)
        resp = client.post("/api/chat/stream", json={"message": "oi", "session_id": "s1"})
        assert resp.status_code == 200
        assert ": ping" in resp.text
        # O keep-alive não engole o stream: os eventos chegam depois dele.
        assert resp.text.index(": ping") < resp.text.index('"content": "Olá')
        assert '"type": "done"' in resp.text
    finally:
        app.dependency_overrides.clear()


def test_delete_memory_returns_204() -> None:
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.delete(f"/api/memories/{_MEMORY_ID}")
        assert resp.status_code == 204
        memory.delete.assert_awaited_once_with(_MEMORY_ID)
    finally:
        app.dependency_overrides.clear()


def test_get_memory_returns_memory_by_id() -> None:
    memory = _memory_mock()
    memory.get.return_value = StoredMemory(
        id="abc",
        text="sobre DI",
        metadata=MemoryMetadata(
            topic="fastapi", source="livro", date=date(2026, 8, 25), session_id="s1"
        ),
    )
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get(f"/api/memories/{_MEMORY_ID}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == "abc"
        memory.get.assert_awaited_once_with(_MEMORY_ID)
    finally:
        app.dependency_overrides.clear()


def test_get_memory_404_when_missing() -> None:
    memory = AsyncMock()
    memory.get.return_value = None
    store = AsyncMock()
    store.ping.return_value = True
    app.dependency_overrides[get_memory_service] = lambda: memory
    app.dependency_overrides[get_vector_store] = lambda: store
    try:
        client = TestClient(app)
        resp = client.get(f"/api/memories/{_MEMORY_ID}")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_get_memory_503_when_storage_unavailable() -> None:
    """Qdrant offline + memória não encontrada ⇒ 503, não 404 (não mente "apagada")."""
    memory = AsyncMock()
    memory.get.return_value = None
    store = AsyncMock()
    store.ping.return_value = False
    app.dependency_overrides[get_memory_service] = lambda: memory
    app.dependency_overrides[get_vector_store] = lambda: store
    try:
        client = TestClient(app)
        resp = client.get(f"/api/memories/{_MEMORY_ID}")
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_delete_memory_503_when_storage_unavailable() -> None:
    """Qdrant offline ⇒ DELETE não mente 204 (a memória pode ter sobrevivido)."""
    memory = _memory_mock()
    memory.delete.return_value = False
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.delete(f"/api/memories/{_MEMORY_ID}")
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_memory_id_malformado_vira_422_e_nao_503() -> None:
    """Id que não é UUID ⇒ 422 em GET/DELETE/PATCH, sem tocar o serviço.

    Com o id como texto livre, "nao-e-uuid" ia até o Qdrant, que o rejeitava
    ("not a valid point ID"); o `MemoryService` trata qualquer exceção como
    armazenamento indisponível e o DELETE/PATCH respondiam 503 — dizendo ao
    cliente que o banco vetorial estava fora quando o erro era o id.
    """
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        assert client.delete("/api/memories/nao-e-uuid").status_code == 422
        assert client.get("/api/memories/nao-e-uuid").status_code == 422
        assert client.patch("/api/memories/nao-e-uuid", json={"text": "novo"}).status_code == 422
        memory.delete.assert_not_awaited()
        memory.get.assert_not_awaited()
        memory.update.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


def test_delete_session_503_when_storage_unavailable() -> None:
    """Qdrant offline ⇒ DELETE /sessions não mente 204."""
    memory = _memory_mock()
    memory.delete_session.return_value = False
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.delete("/api/sessions/sess-1")
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_delete_session_returns_204() -> None:
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.delete("/api/sessions/sess-1")
        assert resp.status_code == 204
        memory.delete_session.assert_awaited_once_with("sess-1")
    finally:
        app.dependency_overrides.clear()


def test_create_memory_returns_201() -> None:
    memory = _memory_mock()
    memory.store.return_value = ("new-1", True)
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/memories",
            json={"text": "aprendi X", "topic": "react", "source": "nota", "session_id": "s1"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["id"] == "new-1"
        assert body["persisted"] is True
        assert body["metadata"]["topic"] == "react"
    finally:
        app.dependency_overrides.clear()


def test_create_memory_reports_unpersisted() -> None:
    memory = _memory_mock()
    memory.store.return_value = ("new-2", False)
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/memories",
            json={"text": "ficou sem qdrant", "topic": "x", "source": "y", "session_id": "s2"},
        )
        assert resp.status_code == 201
        assert resp.json()["persisted"] is False
    finally:
        app.dependency_overrides.clear()


def test_create_memory_rejects_oversized_topic() -> None:
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/memories",
            json={"text": "ok", "topic": "x" * 121, "source": "y", "session_id": "s3"},
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_create_memory_returns_502_when_embedding_fails() -> None:
    """Falha de embedding (OpenAI) no POST /api/memories vira 502, não 500 cru."""
    from openai import OpenAIError

    memory = AsyncMock()
    memory.canonical_topic.return_value = "react"
    memory.store.side_effect = OpenAIError("embedding api down")
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/memories",
            json={"text": "aprendi X", "topic": "react", "source": "nota", "session_id": "s1"},
        )
        assert resp.status_code == 502
        assert "embedding api down" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_create_memory_returns_502_on_non_openai_failure() -> None:
    """Erro não-OpenAI no POST /api/memories vira 502, não 500 cru (nunca 500)."""
    memory = AsyncMock()
    memory.canonical_topic.return_value = "react"
    memory.store.side_effect = IndexError("embedding vazio")
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/memories",
            json={"text": "x", "topic": "t", "source": "s", "session_id": "s1"},
        )
        assert resp.status_code == 502
    finally:
        app.dependency_overrides.clear()


def test_list_memories_rejects_oversized_topic() -> None:
    """`topic` acima de 120 no filtro (GET) é rejeitado (422), como `session_id`."""
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/memories?topic=" + "x" * 121)
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_create_memory_rejects_blank_topic() -> None:
    """Metadata (topic/source/session_id) só com espaços é rejeitada (422)."""
    memory = AsyncMock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/memories",
            json={"text": "ok", "topic": "  ", "source": "y", "session_id": "s4"},
        )
        assert resp.status_code == 422
        memory.store.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


def test_create_memory_rejects_blank_text() -> None:
    """Texto só com espaços é rejeitado (422) — não gera embedding-lixo."""
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/memories",
            json={"text": "   ", "topic": "x", "source": "y", "session_id": "s4"},
        )
        assert resp.status_code == 422
        memory.store.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


def test_chat_stream_emits_error_event_on_non_openai_failure() -> None:
    """Exceção não-OpenAI no stream vira evento de erro SSE (nunca stream truncado)."""

    class _BrokenStream:
        async def stream_chat(
            self,
            message: str,
            session_id: str,
            topic: str | None = None,
            *,
            model: str | None = None,
        ):
            del message, session_id, topic
            yield StreamEvent(type="token", content="oi")
            raise RuntimeError("boom")

    app.dependency_overrides[get_agent_service] = lambda: _BrokenStream()
    try:
        client = TestClient(app)
        resp = client.post("/api/chat/stream", json={"message": "oi", "session_id": "s1"})
        assert resp.status_code == 200
        assert '"type": "error"' in resp.text
        assert '"type": "done"' not in resp.text
    finally:
        app.dependency_overrides.clear()


def test_chat_rejects_blank_message() -> None:
    """Mensagem só com espaços é rejeitada (422)."""
    app.dependency_overrides[get_agent_service] = lambda: AsyncMock()
    try:
        client = TestClient(app)
        resp = client.post("/api/chat", json={"message": "   ", "session_id": "s1"})
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_deep_health_reports_qdrant_status() -> None:
    store = AsyncMock()
    store.ping.return_value = True
    app.dependency_overrides[get_vector_store] = lambda: store
    try:
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "ok"
        assert body["dependencies"]["qdrant"] == "up"
    finally:
        app.dependency_overrides.clear()


def test_readiness_200_when_qdrant_answers() -> None:
    """`/health/ready` é o alvo do healthcheck do Compose: 200 com Qdrant de pé."""
    store = AsyncMock()
    store.ping.return_value = True
    app.dependency_overrides[get_vector_store] = lambda: store
    try:
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 200, resp.text
        assert resp.json()["dependencies"]["qdrant"] == "up"
    finally:
        app.dependency_overrides.clear()


def test_readiness_503_when_qdrant_is_down() -> None:
    """Qdrant fora ⇒ 503, para o container parar de se dizer "healthy".

    Antes o healthcheck mirava `/health`, que responde 200 fixo: o Compose
    mostrava "healthy" com o banco vetorial caído.
    """
    store = AsyncMock()
    store.ping.return_value = False
    app.dependency_overrides[get_vector_store] = lambda: store
    try:
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 503, resp.text
        assert resp.json()["status"] == "degraded"
        assert resp.json()["dependencies"]["qdrant"] == "down"
    finally:
        app.dependency_overrides.clear()


def test_liveness_stays_ok_when_qdrant_is_down() -> None:
    """Liveness continua 200: dependência fora não derruba processo saudável."""
    store = AsyncMock()
    store.ping.return_value = False
    app.dependency_overrides[get_vector_store] = lambda: store
    try:
        client = TestClient(app)
        assert client.get("/health").status_code == 200
    finally:
        app.dependency_overrides.clear()


# --- Provedor do LLM ausente: 503 estruturado, nunca 500 cru ---


def _unconfigured_agent_service() -> AgentService:
    """AgentService real com config sem credencial (o agente não inicializa)."""
    from app.core.config import Settings

    return AgentService(
        memory_service=AsyncMock(),  # type: ignore[arg-type]
        config=Settings(openai_api_key="", openai_base_url=None),
    )


def test_chat_returns_503_when_provider_is_not_configured() -> None:
    """Regressão: a dependência levantava na resolução e virava 500 cru."""
    app.dependency_overrides[get_agent_service] = _unconfigured_agent_service
    try:
        client = TestClient(app)
        resp = client.post("/api/chat", json={"message": "oi", "session_id": "s1"})
        assert resp.status_code == 503, resp.text
        assert "provedor" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_chat_stream_emits_error_event_when_provider_is_not_configured() -> None:
    app.dependency_overrides[get_agent_service] = _unconfigured_agent_service
    try:
        client = TestClient(app)
        resp = client.post("/api/chat/stream", json={"message": "oi", "session_id": "s1"})
        assert resp.status_code == 200
        assert '"type": "error"' in resp.text
        assert "provedor" in resp.text
    finally:
        app.dependency_overrides.clear()


# --- Grafia canônica de tópico no POST /api/memories ---


def test_create_memory_echoes_canonical_topic() -> None:
    """Tópico com caixa diferente da existente é gravado com a grafia já usada."""
    memory = _memory_mock()
    memory.canonical_topic.side_effect = None
    memory.canonical_topic.return_value = "fastapi"  # grafia já existente
    memory.store.return_value = ("novo-id", True)
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/memories",
            json={"text": "sobre DI", "topic": "FastAPI", "source": "livro", "session_id": "s1"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["metadata"]["topic"] == "fastapi"
        memory.canonical_topic.assert_awaited_once_with("FastAPI")
        payload = memory.store.await_args.args[1]
        assert payload.topic == "fastapi"
    finally:
        app.dependency_overrides.clear()


# --- Limiar do recall na busca HTTP ---


def test_search_uses_configured_recall_threshold(monkeypatch) -> None:
    """Sem `min_score` na query, a rota usa o limiar configurado (não um 0.7 fixo)."""
    from types import SimpleNamespace

    memory = _memory_mock()
    memory.recall.return_value = []
    monkeypatch.setattr(
        "app.api.routers.memories.settings",
        SimpleNamespace(recall_score_threshold=0.42),
    )
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/memories/search?q=di")
        assert resp.status_code == 200, resp.text
        memory.recall.assert_awaited_once_with("di", 10, 0.42, None, session_id=None)
    finally:
        app.dependency_overrides.clear()


# --- Renomear tópico (PATCH /api/topics) ---


def test_rename_topic_returns_new_name_and_count() -> None:
    """Rename bem-sucedido devolve o nome novo e quantas memórias mudaram."""
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.patch("/api/topics", json={"topic": "fastapi", "name": " FastAPI DI "})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"topic": "FastAPI DI", "updated": 2}
        # O nome é normalizado (trim) antes de chegar ao serviço.
        memory.rename_topic.assert_awaited_once_with("fastapi", "FastAPI DI")
    finally:
        app.dependency_overrides.clear()


def test_search_honours_explicit_min_score() -> None:
    memory = _memory_mock()
    memory.recall.return_value = []
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/memories/search?q=di&min_score=0.9")
        assert resp.status_code == 200, resp.text
        memory.recall.assert_awaited_once_with("di", 10, 0.9, None, session_id=None)
    finally:
        app.dependency_overrides.clear()


def test_rename_topic_404_when_source_missing() -> None:
    memory = _memory_mock()
    memory.rename_topic.return_value = RenameTopicResult(status=RenameTopicStatus.NOT_FOUND)
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.patch("/api/topics", json={"topic": "inexistente", "name": "novo"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "tópico não encontrado"
    finally:
        app.dependency_overrides.clear()


def test_rename_topic_409_when_name_already_used() -> None:
    """Não funde dois tópicos em silêncio: nome já usado vira 409."""
    memory = _memory_mock()
    memory.rename_topic.return_value = RenameTopicResult(status=RenameTopicStatus.CONFLICT)
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.patch("/api/topics", json={"topic": "fastapi", "name": "react"})
        assert resp.status_code == 409
        assert "react" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_rename_topic_503_when_storage_unavailable() -> None:
    memory = _memory_mock()
    memory.rename_topic.return_value = RenameTopicResult(status=RenameTopicStatus.UNAVAILABLE)
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.patch("/api/topics", json={"topic": "fastapi", "name": "novo"})
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_rename_topic_rejects_blank_name() -> None:
    """Nome só com espaços não vira tópico: 422 antes de tocar o armazenamento."""
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.patch("/api/topics", json={"topic": "fastapi", "name": "   "})
        assert resp.status_code == 422
        memory.rename_topic.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


# --- Editar memória (PATCH /api/memories/{id}) ---


def _updated() -> StoredMemory:
    return StoredMemory(
        id="abc",
        text="texto novo",
        metadata=MemoryMetadata(
            topic="fastapi", source="livro", date=date(2026, 8, 25), session_id="s1"
        ),
    )


def test_update_memory_returns_updated_memory() -> None:
    """PATCH devolve 200 com a memória já contendo o texto novo."""
    from app.services.memory_service import UpdateMemoryResult, UpdateMemoryStatus

    memory = _memory_mock()
    memory.update.return_value = UpdateMemoryResult(
        status=UpdateMemoryStatus.UPDATED, memory=_updated()
    )
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.patch(f"/api/memories/{_MEMORY_ID}", json={"text": "texto novo"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["text"] == "texto novo"
        memory.update.assert_awaited_once_with(_MEMORY_ID, "texto novo")
    finally:
        app.dependency_overrides.clear()


def test_update_memory_404_when_missing() -> None:
    from app.services.memory_service import UpdateMemoryResult, UpdateMemoryStatus

    memory = _memory_mock()
    memory.update.return_value = UpdateMemoryResult(status=UpdateMemoryStatus.NOT_FOUND)
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.patch(f"/api/memories/{_MEMORY_ID}", json={"text": "novo"})
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_update_memory_503_when_storage_unavailable() -> None:
    """Qdrant offline ⇒ 503 (não mente sucesso nem 404)."""
    from app.services.memory_service import UpdateMemoryResult, UpdateMemoryStatus

    memory = _memory_mock()
    memory.update.return_value = UpdateMemoryResult(status=UpdateMemoryStatus.UNAVAILABLE)
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.patch(f"/api/memories/{_MEMORY_ID}", json={"text": "novo"})
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_update_memory_502_when_embedding_fails() -> None:
    """Falha de embedding (OpenAI) no PATCH vira 502, não 500 cru."""
    from openai import OpenAIError

    memory = _memory_mock()
    memory.update.side_effect = OpenAIError("embedding api down")
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.patch(f"/api/memories/{_MEMORY_ID}", json={"text": "novo"})
        assert resp.status_code == 502
        assert "embedding api down" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_update_memory_502_when_service_returns_updated_without_memory() -> None:
    """`UPDATED` sem memória vira 502 estruturado, não AssertionError cru (500).

    O router tinha um `assert result.memory is not None`: um estado inconsistente
    do service saía como 500 com traceback (fora dos 502/503 do contrato) e, com
    `python -O`, o `assert` sumia e o `response_model` estourava com outro 500.
    """
    from app.services.memory_service import UpdateMemoryResult, UpdateMemoryStatus

    memory = _memory_mock()
    memory.update.return_value = UpdateMemoryResult(status=UpdateMemoryStatus.UPDATED)
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.patch(f"/api/memories/{_MEMORY_ID}", json={"text": "novo"})
        assert resp.status_code == 502, resp.text
        assert "não foi devolvida" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_update_memory_rejects_blank_text() -> None:
    """Texto só com espaços é rejeitado (422) antes de tocar o serviço."""
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.patch(f"/api/memories/{_MEMORY_ID}", json={"text": "   "})
        assert resp.status_code == 422
        memory.update.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


# --- Busca (GET /api/memories/search): falha de embedding nunca vira 500 ---


def test_search_memories_returns_502_when_embedding_fails() -> None:
    """Falha de embedding (OpenAI) na busca vira 502, não o 500 que saía cru."""
    from openai import OpenAIError

    memory = _memory_mock()
    memory.recall.side_effect = OpenAIError("embedding api down")
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/memories/search?q=di")
        assert resp.status_code == 502
        assert "embedding api down" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_search_memories_returns_502_on_non_openai_failure() -> None:
    """Erro não-OpenAI na busca também vira 502 estruturado (nunca 500 cru)."""
    memory = _memory_mock()
    memory.recall.side_effect = RuntimeError("boom")
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/memories/search?q=di")
        assert resp.status_code == 502
    finally:
        app.dependency_overrides.clear()


# --- Paginação por cursor da listagem (GET /api/memories) ---


def test_list_memories_exposes_next_cursor_header() -> None:
    """Quando há mais páginas, o próximo cursor vem no header X-Next-Cursor."""
    memory = _memory_mock()
    memory.list.return_value = ([_updated()], "11111111-1111-1111-1111-111111111111")
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/memories?limit=1")
        assert resp.status_code == 200, resp.text
        assert resp.headers.get("x-next-cursor") == "11111111-1111-1111-1111-111111111111"
        assert resp.json()[0]["id"] == "abc"
    finally:
        app.dependency_overrides.clear()


def test_list_memories_forwards_cursor_and_rejects_malformed() -> None:
    """Cursor válido é repassado; malformado vira 422 e nem chega ao serviço."""
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        valid = "11111111-1111-1111-1111-111111111111"
        ok = client.get(f"/api/memories?cursor={valid}")
        assert ok.status_code == 200, ok.text
        assert memory.list.await_args.kwargs["cursor"] == valid

        bad = client.get("/api/memories?cursor=not-a-uuid")
        assert bad.status_code == 422
        memory.list.assert_awaited_once()  # o malformado nem chega ao serviço
    finally:
        app.dependency_overrides.clear()


# --- Apagar um tópico inteiro (DELETE /api/topics) ---


def test_delete_topic_returns_204() -> None:
    """DELETE /api/topics?topic= remove todas as memórias do tópico."""
    memory = _memory_mock()
    memory.delete_topic.return_value = True
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.delete("/api/topics?topic=fastapi")
        assert resp.status_code == 204
        memory.delete_topic.assert_awaited_once_with("fastapi")
    finally:
        app.dependency_overrides.clear()


def test_delete_topic_503_when_storage_unavailable() -> None:
    """Qdrant offline ⇒ DELETE /api/topics não mente 204."""
    memory = _memory_mock()
    memory.delete_topic.return_value = False
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.delete("/api/topics?topic=fastapi")
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()


# --- Total na listagem (X-Total-Count) ---


def test_list_memories_exposes_total_count_header() -> None:
    """A listagem traz X-Total-Count com o total de memórias que casam com o filtro."""
    memory = _memory_mock()
    memory.count.return_value = 42
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/memories?topic=fastapi")
        assert resp.status_code == 200, resp.text
        assert resp.headers.get("x-total-count") == "42"
        assert memory.count.await_args.kwargs["topic"] == "fastapi"
    finally:
        app.dependency_overrides.clear()


def test_list_memories_returns_503_when_storage_unavailable() -> None:
    """Qdrant fora (count=None) ⇒ 503, não 200 sem X-Total-Count.

    Antes a rota devolvia `200 []` sem o header: o cliente não tinha como
    distinguir "você não tem memórias" de "o banco vetorial não respondeu" — e
    concluía que o histórico tinha sumido. O GET por id e o export já devolviam
    503 no mesmo cenário; a listagem passou a seguir o mesmo contrato.
    """
    memory = _memory_mock()
    memory.count.return_value = None
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/memories")
        assert resp.status_code == 503, resp.text
        assert resp.headers.get("x-total-count") is None
    finally:
        app.dependency_overrides.clear()


def test_chat_forwards_model_override() -> None:
    """`model` no corpo é repassado ao agente (override só desta execução)."""
    agent = _agent_mock()
    app.dependency_overrides[get_agent_service] = lambda: agent
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/chat",
            json={"message": "oi", "session_id": "s1", "model": "gpt-4o"},
        )
        assert resp.status_code == 200, resp.text
        agent.chat.assert_awaited_once_with("oi", "s1", None, model="gpt-4o")
    finally:
        app.dependency_overrides.clear()


def test_chat_blank_model_falls_back_to_configured() -> None:
    """`model` só com espaços = modelo configurado (não um nome em branco no upstream)."""
    agent = _agent_mock()
    app.dependency_overrides[get_agent_service] = lambda: agent
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/chat",
            json={"message": "oi", "session_id": "s1", "model": "   "},
        )
        assert resp.status_code == 200, resp.text
        agent.chat.assert_awaited_once_with("oi", "s1", None, model=None)
    finally:
        app.dependency_overrides.clear()


def test_chat_rejects_oversized_model_name() -> None:
    """Nome de modelo acima do limite da coluna/upstream é rejeitado (422)."""
    app.dependency_overrides[get_agent_service] = lambda: AsyncMock()
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/chat",
            json={"message": "oi", "session_id": "s1", "model": "m" * 201},
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


class _TimeoutAgent:
    """AgentService cujo `chat` estoura o teto de tempo do provedor."""

    async def chat(self, *args: object, **kwargs: object) -> ChatResult:
        del args, kwargs
        raise AgentTimeoutError("o provedor não respondeu em 120s")


class _StreamTimeoutAgent:
    """Já emitiu um token quando o teto estourou (caso real do streaming)."""

    async def stream_chat(self, *args: object, **kwargs: object):
        del args, kwargs
        yield StreamEvent(type="token", content="parcial")
        raise AgentTimeoutError("o provedor não respondeu em 120s")


def test_chat_timeout_is_504_not_502() -> None:
    """Provedor que não responde é Gateway Timeout (504), não "erro interno"."""
    app.dependency_overrides[get_agent_service] = lambda: _TimeoutAgent()
    try:
        client = TestClient(app)
        resp = client.post("/api/chat", json={"message": "oi", "session_id": "s1"})
        assert resp.status_code == 504, resp.text
        assert "não respondeu a tempo" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_chat_stream_timeout_emits_error_event() -> None:
    """No stream os headers já saíram (200); o timeout vira evento de erro."""
    app.dependency_overrides[get_agent_service] = lambda: _StreamTimeoutAgent()
    try:
        client = TestClient(app)
        resp = client.post("/api/chat/stream", json={"message": "oi", "session_id": "s1"})
        assert resp.status_code == 200, resp.text
        events = [
            json.loads(line[len("data: "):])
            for line in resp.text.splitlines()
            if line.startswith("data: ")
        ]
        assert events[0]["type"] == "token"
        assert events[-1]["type"] == "error"
        assert "não respondeu a tempo" in events[-1]["detail"]
    finally:
        app.dependency_overrides.clear()


# --- Export de memórias (GET /api/memories/export) ---


def _stored(memory_id: str, text: str, topic: str = "fastapi") -> StoredMemory:
    """Memória persistida de exemplo para os testes do export."""
    return StoredMemory(
        id=memory_id,
        text=text,
        metadata=MemoryMetadata(
            topic=topic, source="livro", date=date(2026, 8, 25), session_id="s1"
        ),
    )


def _store_mock(available: bool = True) -> AsyncMock:
    """VectorStore falso: só o `ping` importa para o desfecho do export."""
    store = AsyncMock()
    store.ping.return_value = available
    return store


def test_export_memories_json_paginates_and_sets_attachment() -> None:
    """Export varre todas as páginas por cursor e devolve um anexo JSON reimportável."""
    memory = AsyncMock()
    memory.list.side_effect = [
        ([_stored("a", "primeira")], "cursor-2"),
        ([_stored("b", "segunda")], None),
    ]
    store = _store_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    app.dependency_overrides[get_vector_store] = lambda: store
    try:
        client = TestClient(app)
        resp = client.get("/api/memories/export")
        assert resp.status_code == 200, resp.text
        assert 'attachment; filename="memorias.json"' == resp.headers["content-disposition"]
        body = resp.json()
        assert [item["id"] for item in body] == ["a", "b"]
        assert body[0]["metadata"]["topic"] == "fastapi"

        # Duas páginas: a segunda foi pedida com o cursor devolvido pela primeira.
        assert [call.kwargs["cursor"] for call in memory.list.await_args_list] == [None, "cursor-2"]
    finally:
        app.dependency_overrides.clear()


def test_export_memories_markdown_is_readable() -> None:
    """`format=markdown` gera o texto legível com a metadata de cada memória."""
    memory = AsyncMock()
    memory.list.return_value = ([_stored("a", "conteúdo da memória")], None)
    app.dependency_overrides[get_memory_service] = lambda: memory
    app.dependency_overrides[get_vector_store] = lambda: _store_mock()
    try:
        client = TestClient(app)
        resp = client.get("/api/memories/export", params={"format": "markdown"})
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/markdown")
        assert "## fastapi" in resp.text
        assert "- fonte: livro" in resp.text
        assert "conteúdo da memória" in resp.text
    finally:
        app.dependency_overrides.clear()


def test_export_memories_forwards_filters() -> None:
    """`topic`/`session_id` do export chegam ao serviço (recorte do backup)."""
    memory = AsyncMock()
    memory.list.return_value = ([], None)
    app.dependency_overrides[get_memory_service] = lambda: memory
    app.dependency_overrides[get_vector_store] = lambda: _store_mock()
    try:
        client = TestClient(app)
        resp = client.get(
            "/api/memories/export", params={"topic": "react", "session_id": "s9"}
        )
        assert resp.status_code == 200, resp.text
        kwargs = memory.list.await_args_list[0].kwargs
        assert kwargs["topic"] == "react"
        assert kwargs["session_id"] == "s9"
    finally:
        app.dependency_overrides.clear()


def test_export_memories_503_when_storage_is_down() -> None:
    """Qdrant fora → 503; nunca um arquivo vazio que pareça "não havia nada"."""
    memory = AsyncMock()
    memory.list.return_value = ([], None)
    app.dependency_overrides[get_memory_service] = lambda: memory
    app.dependency_overrides[get_vector_store] = lambda: _store_mock(available=False)
    try:
        client = TestClient(app)
        resp = client.get("/api/memories/export")
        assert resp.status_code == 503, resp.text
        assert "indisponível" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_export_memories_empty_but_healthy_returns_empty_list() -> None:
    """Sem memórias e com storage respondendo, o export é um [] legítimo."""
    memory = AsyncMock()
    memory.list.return_value = ([], None)
    store = _store_mock(available=True)
    app.dependency_overrides[get_memory_service] = lambda: memory
    app.dependency_overrides[get_vector_store] = lambda: store
    try:
        client = TestClient(app)
        resp = client.get("/api/memories/export")
        assert resp.status_code == 200, resp.text
        assert resp.json() == []
        store.ping.assert_awaited()
    finally:
        app.dependency_overrides.clear()


def test_export_memories_stops_when_cursor_repeats() -> None:
    """Cursor que se repete encerra o loop (sem isso o export nunca terminaria)."""
    memory = AsyncMock()
    memory.list.return_value = ([_stored("a", "x")], "mesmo-cursor")
    app.dependency_overrides[get_memory_service] = lambda: memory
    app.dependency_overrides[get_vector_store] = lambda: _store_mock()
    try:
        client = TestClient(app)
        resp = client.get("/api/memories/export")
        assert resp.status_code == 200, resp.text
        assert len(memory.list.await_args_list) == 2
    finally:
        app.dependency_overrides.clear()


def test_export_memories_503_when_storage_fails_mid_scan() -> None:
    """Qdrant cai NO MEIO da varredura → 503, nunca um backup PARCIAL com 200.

    `MemoryService.list` engole a exceção do Qdrant e devolve `([], None)` — que
    é indistinguível de "fim da coleção". Sem esta checagem, o export parava na
    página onde o store falhou e devolvia 200 com o que já tinha coletado: o
    usuário salvava um arquivo truncado acreditando ter tudo, apagava o
    tópico/sessão e só descobria a perda depois (o backup não serve de backup).
    """
    memory = AsyncMock()
    memory.list.side_effect = [
        ([_stored("a", "primeira")], "cursor-2"),
        ([], None),  # falha do Qdrant a partir daqui: list degrada para ([], None)
    ]
    store = _store_mock(available=False)
    app.dependency_overrides[get_memory_service] = lambda: memory
    app.dependency_overrides[get_vector_store] = lambda: store
    try:
        client = TestClient(app)
        resp = client.get("/api/memories/export")
        assert resp.status_code == 503, resp.text
        assert "durante o export" in resp.json()["detail"]
        # O arquivo parcial NÃO é entregue: melhor um 503 explícito que um
        # "backup" incompleto com cara de completo.
        assert "content-disposition" not in resp.headers
    finally:
        app.dependency_overrides.clear()


def test_export_memories_rejects_unknown_format() -> None:
    """`format` é Literal: valor desconhecido é 422, não um arquivo no formato errado."""
    memory = AsyncMock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    app.dependency_overrides[get_vector_store] = lambda: _store_mock()
    try:
        client = TestClient(app)
        resp = client.get("/api/memories/export", params={"format": "csv"})
        assert resp.status_code == 422
        memory.list.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()

def test_list_memories_with_zero_results_stays_200() -> None:
    """Zero memórias de verdade (count=0, não None) continua 200 com total 0."""
    memory = _memory_mock()
    memory.list.return_value = ([], None)
    memory.count.return_value = 0
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/memories")
        assert resp.status_code == 200, resp.text
        assert resp.json() == []
        assert resp.headers["x-total-count"] == "0"
    finally:
        app.dependency_overrides.clear()
