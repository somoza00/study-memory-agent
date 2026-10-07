"""Testa o provedor de embeddings: remoto (OpenAI-compatível) e local (ONNX).

Embeddings e agente podem apontar para provedores diferentes (ex.: agente no
OpenCode Go, que só expõe `/chat/completions`, e embeddings locais). Sem
`EMBEDDING_BASE_URL`, herda `OPENAI_BASE_URL` — o comportamento anterior a esta
separação, para não quebrar setup self-hosted.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.services.embedding_service import EmbeddingService


class _FakeLocalModel:
    """Embedder local falso: devolve vetores constantes da dimensão pedida."""

    def __init__(self, dim: int) -> None:
        self._dim = dim
        self.calls: list[list[str]] = []

    def embed(self, documents: Iterable[str]) -> Iterable[Sequence[float]]:
        batch = list(documents)
        self.calls.append(batch)
        return [[0.5] * self._dim for _ in batch]


def _remote_client(embedding: list[float]) -> AsyncMock:
    client = AsyncMock()
    client.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(embedding=embedding)]
    )
    return client


# --- Provedor remoto (OpenAI-compatível) ---


def test_embedding_base_url_wins_over_agent_base_url() -> None:
    """`EMBEDDING_BASE_URL` tem precedência: separa o provedor de embeddings."""
    cfg = Settings(
        openai_api_key="x",
        openai_base_url="https://opencode.ai/zen/v1",
        embedding_base_url="http://localhost:11434/v1",
    )
    client = EmbeddingService(config=cfg)._get_client()
    assert str(client.base_url).startswith("http://localhost:11434/v1")


def test_embedding_base_url_falls_back_to_agent_base_url() -> None:
    """Sem `EMBEDDING_BASE_URL`, herda `OPENAI_BASE_URL` (compatibilidade)."""
    cfg = Settings(openai_api_key="x", openai_base_url="http://localhost:11434/v1")
    client = EmbeddingService(config=cfg)._get_client()
    assert str(client.base_url).startswith("http://localhost:11434/v1")


def test_embedding_client_defaults_to_openai_when_unset() -> None:
    """Sem nenhum base URL, mantém o endpoint padrão da OpenAI (sem regressão)."""
    cfg = Settings(openai_api_key="x")
    client = EmbeddingService(config=cfg)._get_client()
    assert "api.openai.com" in str(client.base_url)


def test_embedding_key_falls_back_to_agent_key() -> None:
    """Sem `EMBEDDING_API_KEY`, os embeddings usam a chave do agente."""
    cfg = Settings(openai_api_key="chave-do-agente")
    client = EmbeddingService(config=cfg)._get_client()
    assert client.api_key == "chave-do-agente"


def test_embedding_key_overrides_agent_key() -> None:
    """`EMBEDDING_API_KEY` permite credencial distinta da do agente."""
    cfg = Settings(openai_api_key="chave-do-agente", embedding_api_key="chave-de-embeddings")
    client = EmbeddingService(config=cfg)._get_client()
    assert client.api_key == "chave-de-embeddings"


async def test_remote_provider_returns_vector_from_endpoint() -> None:
    """Provedor remoto (default) usa `/embeddings` do endpoint configurado."""
    cfg = Settings(openai_api_key="x", embedding_dim=3)
    client = _remote_client([0.1, 0.2, 0.3])
    service = EmbeddingService(client=client, config=cfg)

    assert await service.embed("texto") == [0.1, 0.2, 0.3]
    client.embeddings.create.assert_awaited_once_with(
        input="texto", model="text-embedding-3-small"
    )


# --- Provedor local (ONNX) ---


async def test_local_provider_uses_injected_model_without_network() -> None:
    """`EMBEDDING_PROVIDER=local` gera o vetor no processo (sem chave/rede)."""
    cfg = Settings(embedding_provider="local", embedding_dim=4)
    model = _FakeLocalModel(4)
    service = EmbeddingService(config=cfg, local_model=model)

    assert await service.embed("memória de estudo") == [0.5, 0.5, 0.5, 0.5]
    assert model.calls == [["memória de estudo"]]


async def test_local_provider_ignores_remote_endpoint() -> None:
    """Com provedor local, nem o cliente remoto é criado (sem chave)."""
    cfg = Settings(embedding_provider="local", embedding_dim=2, embedding_base_url="http://x/v1")
    service = EmbeddingService(config=cfg, local_model=_FakeLocalModel(2))

    await service.embed("texto")

    assert service._client is None


# --- Guarda de dimensão ---


async def test_local_dim_mismatch_raises_clear_error() -> None:
    """Modelo local com dimensão diferente de `EMBEDDING_DIM` falha explícito."""
    cfg = Settings(embedding_provider="local", embedding_dim=16)
    service = EmbeddingService(config=cfg, local_model=_FakeLocalModel(8))

    with pytest.raises(ValueError, match="EMBEDDING_DIM=16"):
        await service.embed("texto")


async def test_remote_dim_mismatch_raises_clear_error() -> None:
    """Mesma guarda no provedor remoto: evita erro obscuro do Qdrant."""
    cfg = Settings(openai_api_key="x", embedding_dim=1536)
    service = EmbeddingService(client=_remote_client([0.1, 0.2]), config=cfg)

    with pytest.raises(ValueError, match="EMBEDDING_DIM=1536"):
        await service.embed("texto")
