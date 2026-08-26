"""Testes do `AgentService` com o agente Pydantic AI mockado.

Não se chama LLM: `_build_agent` é substituído por um `AsyncMock`, e o
`MemoryService` também é mockado. Verifica o fluxo recall → response.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

from app.models.memory import MemoryMetadata, MemoryResult
from app.services.agent_service import AgentService, ChatResult


def _memory_mock() -> tuple[AsyncMock, list[MemoryResult]]:
    memory = AsyncMock()
    metadata = MemoryMetadata(
        topic="fastapi", source="livro", date=date(2026, 8, 25), session_id="s1"
    )
    results = [MemoryResult(id="abc", text="sobre DI", score=0.9, metadata=metadata)]
    memory.recall.return_value = results
    return memory, results


async def test_chat_recalls_memories_and_returns_response() -> None:
    memory, _results = _memory_mock()
    fake_agent = AsyncMock()
    run_result = AsyncMock()
    run_result.output = "Resposta do agente."
    fake_agent.run.return_value = run_result

    with patch.object(AgentService, "_build_agent", return_value=fake_agent):
        service = AgentService(memory_service=memory)  # type: ignore[arg-type]
        result = await service.chat("o que é DI no FastAPI?", session_id="s1")

    assert isinstance(result, ChatResult)
    assert result.response == "Resposta do agente."
    assert result.memories_used == 1
    memory.recall.assert_awaited_once_with("o que é DI no FastAPI?", 5, 0.7)
    fake_agent.run.assert_awaited_once()


async def test_chat_with_no_memories_reports_zero() -> None:
    memory = AsyncMock()
    memory.recall.return_value = []
    fake_agent = AsyncMock()
    run_result = AsyncMock()
    run_result.output = "Sem contexto, mas respondo mesmo assim."
    fake_agent.run.return_value = run_result

    with patch.object(AgentService, "_build_agent", return_value=fake_agent):
        service = AgentService(memory_service=memory)  # type: ignore[arg-type]
        result = await service.chat("quem foi Euclides?", session_id="s2")

    assert result.memories_used == 0
    assert result.response == "Sem contexto, mas respondo mesmo assim."