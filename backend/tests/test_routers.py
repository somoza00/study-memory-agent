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
from app.services.agent_service import AgentService, ChatResult, StreamEvent
from app.services.memory_service import RenameTopicResult, RenameTopicStatus


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
    store = AsyncMock()
    store.ping.return_value = True
    app.dependency_overrides[get_memory_service] = lambda: memory
    app.dependency_overrides[get_vector_store] = lambda: store
    try:
        client = TestClient(app)
        resp = client.get("/api/memories/xyz")
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
        resp = client.get("/api/memories/xyz")
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
        resp = client.delete("/api/memories/abc")
        assert resp.status_code == 503
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
        resp = client.patch("/api/memories/abc", json={"text": "texto novo"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["text"] == "texto novo"
        memory.update.assert_awaited_once_with("abc", "texto novo")
    finally:
        app.dependency_overrides.clear()


def test_update_memory_404_when_missing() -> None:
    from app.services.memory_service import UpdateMemoryResult, UpdateMemoryStatus

    memory = _memory_mock()
    memory.update.return_value = UpdateMemoryResult(status=UpdateMemoryStatus.NOT_FOUND)
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.patch("/api/memories/xyz", json={"text": "novo"})
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
        resp = client.patch("/api/memories/abc", json={"text": "novo"})
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
        resp = client.patch("/api/memories/abc", json={"text": "novo"})
        assert resp.status_code == 502
        assert "embedding api down" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_update_memory_rejects_blank_text() -> None:
    """Texto só com espaços é rejeitado (422) antes de tocar o serviço."""
    memory = _memory_mock()
    app.dependency_overrides[get_memory_service] = lambda: memory
    try:
        client = TestClient(app)
        resp = client.patch("/api/memories/abc", json={"text": "   "})
        assert resp.status_code == 422
        memory.update.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()