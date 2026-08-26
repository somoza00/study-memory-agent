"""Testes dos routers de chat e memórias com dependências mockadas.

O agente Pydantic AI e o MemoryService são substituídos por `AsyncMock`
via `app.dependency_overrides` — não se testa o LLM, só o roteamento.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.deps import get_agent_service, get_memory_service
from app.main import app
from app.models.memory import MemoryMetadata, StoredMemory
from app.services.agent_service import ChatResult


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
        agent.chat.assert_awaited_once_with("oi", "s1")
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