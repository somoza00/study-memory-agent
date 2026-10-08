"""Testes do `AgentService` com o agente Pydantic AI mockado.

Não se chama LLM: `_build_agent` é substituído por um `AsyncMock`, e o
`MemoryService` também é mockado. Verifica o fluxo recall → response.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.models.memory import MemoryMetadata, MemoryResult
from app.services.agent_service import AgentService, ChatResult, ProviderNotConfiguredError


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
    # Escopo default "all": o recall NÃO filtra por sessão (senão uma conversa
    # nova nunca vê o que foi estudado antes).
    memory.recall.assert_awaited_once_with(
        "o que é DI no FastAPI?", 5, 0.7, None, session_id=None
    )
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


async def test_chat_forwards_topic_filter_to_recall() -> None:
    memory = AsyncMock()
    memory.recall.return_value = []
    fake_agent = AsyncMock()
    run_result = AsyncMock()
    run_result.output = "ok"
    fake_agent.run.return_value = run_result

    with patch.object(AgentService, "_build_agent", return_value=fake_agent):
        service = AgentService(memory_service=memory)  # type: ignore[arg-type]
        await service.chat("sobre vite", session_id="s3", topic="react")

    memory.recall.assert_awaited_once_with("sobre vite", 5, 0.7, "react", session_id=None)


def test_agent_uses_configured_openai_base_url() -> None:
    """`OPENAI_BASE_URL` aponta o agente para um endpoint OpenAI-compatível."""
    from app.core.config import Settings

    cfg = Settings(openai_api_key="x", openai_base_url="http://localhost:11434/v1")
    service = AgentService(memory_service=AsyncMock(), config=cfg)
    base_url = str(service._agent.model.provider.client.base_url)  # type: ignore[attr-defined]
    assert base_url.startswith("http://localhost:11434/v1")


def test_agent_defaults_to_openai_base_url_when_unset() -> None:
    """Sem OPENAI_BASE_URL, o agente usa o endpoint padrão da OpenAI (sem regressão)."""
    from app.core.config import Settings

    cfg = Settings(openai_api_key="x")
    service = AgentService(memory_service=AsyncMock(), config=cfg)
    base_url = str(service._agent.model.provider.client.base_url)  # type: ignore[attr-defined]
    assert "api.openai.com" in base_url


def test_agent_sends_extra_headers_when_configured() -> None:
    """`OPENAI_EXTRA_HEADERS` chega ao provedor (ex.: `x-opencode-session`)."""
    from app.core.config import Settings

    cfg = Settings(
        openai_api_key="x",
        openai_base_url="https://opencode.ai/zen/go/v1",
        openai_extra_headers={"x-opencode-session": "study-memory-agent"},
    )
    service = AgentService(memory_service=AsyncMock(), config=cfg)
    client = service._agent.model.provider.client  # type: ignore[attr-defined]
    assert client.default_headers["x-opencode-session"] == "study-memory-agent"
    assert str(client.base_url).startswith("https://opencode.ai/zen/go/v1")


def test_agent_without_extra_headers_keeps_plain_provider() -> None:
    """Sem headers extras, o caminho simples (api_key/base_url) é preservado."""
    from app.core.config import Settings

    cfg = Settings(openai_api_key="x", openai_base_url="https://opencode.ai/zen/go/v1")
    service = AgentService(memory_service=AsyncMock(), config=cfg)
    client = service._agent.model.provider.client  # type: ignore[attr-defined]
    assert "x-opencode-session" not in client.default_headers


# --- Provedor ausente: serviço sobe, chat responde 503 (nunca 500 cru) ---


def test_service_without_credentials_does_not_raise_on_construction() -> None:
    """Credencial ausente não pode explodir na construção (era o 500 cru do DI)."""
    from app.core.config import Settings

    cfg = Settings(openai_api_key="", openai_base_url=None)
    service = AgentService(memory_service=AsyncMock(), config=cfg)

    assert service._agent is None  # guardou o erro em vez de subir a exceção
    with pytest.raises(ProviderNotConfiguredError):
        service._require_agent()


async def test_chat_without_credentials_raises_provider_not_configured() -> None:
    from app.core.config import Settings

    cfg = Settings(openai_api_key="", openai_base_url=None)
    service = AgentService(memory_service=AsyncMock(), config=cfg)

    with pytest.raises(ProviderNotConfiguredError):
        await service.chat("oi", session_id="s1")


# --- Limiar do recall vem da configuração ---


async def test_chat_uses_provider_default_threshold_for_local_embeddings() -> None:
    """Com embeddings locais o limiar efetivo é 0.55 (não mais o 0.7 fixo)."""
    from app.core.config import Settings

    memory = AsyncMock()
    memory.recall.return_value = []
    fake_agent = AsyncMock()
    run_result = AsyncMock()
    run_result.output = "ok"
    fake_agent.run.return_value = run_result

    with patch.object(AgentService, "_build_agent", return_value=fake_agent):
        service = AgentService(
            memory_service=memory, config=Settings(embedding_provider="local")
        )
        await service.chat("oi", session_id="s1")

    memory.recall.assert_awaited_once_with("oi", 5, 0.55, None, session_id=None)


async def test_chat_honours_explicit_recall_threshold() -> None:
    from app.core.config import Settings

    memory = AsyncMock()
    memory.recall.return_value = []
    fake_agent = AsyncMock()
    run_result = AsyncMock()
    run_result.output = "ok"
    fake_agent.run.return_value = run_result

    with patch.object(AgentService, "_build_agent", return_value=fake_agent):
        service = AgentService(
            memory_service=memory,
            config=Settings(embedding_provider="local", recall_min_score=0.33, recall_limit=2),
        )
        await service.chat("oi", session_id="s1")

    memory.recall.assert_awaited_once_with("oi", 2, 0.33, None, session_id=None)


# --- Escopo do recall ---


async def test_chat_honours_session_scoped_recall() -> None:
    """Com `RECALL_SCOPE=session`, o recall fica restrito à conversa atual."""
    from app.core.config import Settings

    memory = AsyncMock()
    memory.recall.return_value = []
    fake_agent = AsyncMock()
    run_result = AsyncMock()
    run_result.output = "ok"
    fake_agent.run.return_value = run_result

    with patch.object(AgentService, "_build_agent", return_value=fake_agent):
        service = AgentService(
            memory_service=memory, config=Settings(recall_scope="session")
        )
        await service.chat("oi", session_id="s1")

    memory.recall.assert_awaited_once_with("oi", 5, 0.7, None, session_id="s1")