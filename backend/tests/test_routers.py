"""Testes dos routers de chat e memórias com dependências mockadas.

O agente Pydantic AI e o MemoryService são substituídos por `AsyncMock`
via `app.dependency_overrides` — não se testa o LLM, só o roteamento.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.deps import get_agent_service, get_memory_service, get_vector_store
from app.main import app
from app.models.memory import MemoryMetadata, StoredMemory
from app.services.agent_service import ChatResult, StreamEvent


class _FakeStreamAgent:
    """Substituto do AgentService que emite eventos SSE sem tocar o LLM."""

    async def stream_chat(self, message: str, session_id: str, topic: str | None = None):
        del message, session_id, topic
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
    memory.list.return_value = [StoredMemory(id="abc", text="texto", metadata=metadata)]
    memory.list_topics.return_value = ["fastapi", "react"]
    memory.delete.return_value = None
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
        agent.chat.assert_awaited_once_with("oi", "s1", None)
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


def test_delete_memory_returns_204() -> None:
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.delete("/api/memories/abc")
        assert resp.status_code == 204
        memory.delete.assert_awaited_once_with("abc")
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
        resp = client.get("/api/memories/abc")
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == "abc"
        memory.get.assert_awaited_once_with("abc")
    finally:
        app.dependency_overrides.clear()


def test_get_memory_404_when_missing() -> None:
    memory = AsyncMock()
    memory.get.return_value = None
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.get("/api/memories/xyz")
        assert resp.status_code == 404
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
        async def stream_chat(self, message: str, session_id: str, topic: str | None = None):
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