"""Testes do shutdown: os clientes de rede dos singletons precisam fechar.

`VectorStore` (cliente Qdrant) e `EmbeddingService` (cliente OpenAI dos
embeddings) são criados uma vez via `lru_cache` e cada um segura um pool httpx
próprio. Antes o lifespan não tinha shutdown: os pools só eram liberados quando
o processo morria — e em qualquer ciclo de vida por app (testes com lifespan,
reload do uvicorn) sobrava um pool órfão por instância.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.api import deps
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore


class _FakeClient:
    """Cliente mínimo com `close()` — registra se foi fechado."""

    def __init__(self) -> None:
        self.closed = 0

    async def close(self) -> None:
        self.closed += 1


async def test_vector_store_close_closes_qdrant_client() -> None:
    client = _FakeClient()
    store = VectorStore(client=client)  # type: ignore[arg-type]

    await store.close()

    assert client.closed == 1


async def test_embedding_close_is_noop_when_client_never_built() -> None:
    """Provedor `local` nunca cria o cliente remoto: fechar não pode explodir."""
    service = EmbeddingService()

    await service.close()


async def test_embedding_close_closes_lazy_client_once() -> None:
    client = _FakeClient()
    service = EmbeddingService(client=client)  # type: ignore[arg-type]

    await service.close()
    await service.close()  # idempotente: não fecha duas vezes nem levanta

    assert client.closed == 1


async def test_close_services_closes_tracked_singletons(monkeypatch: pytest.MonkeyPatch) -> None:
    """`close_services()` fecha os serviços já instanciados e limpa os caches."""
    store_client = _FakeClient()
    embedding_client = _FakeClient()

    monkeypatch.setattr(
        deps, "VectorStore", lambda: VectorStore(client=store_client)  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        deps,
        "EmbeddingService",
        lambda: EmbeddingService(client=embedding_client),  # type: ignore[arg-type]
    )
    deps.get_vector_store.cache_clear()
    deps.get_embedding_service.cache_clear()
    deps.get_memory_service.cache_clear()
    deps.get_agent_service.cache_clear()

    deps.get_vector_store()
    deps.get_embedding_service()

    await deps.close_services()

    assert store_client.closed == 1
    assert embedding_client.closed == 1
    # Caches limpos: um próximo uso cria instâncias novas (nada fica apontando
    # para clientes já fechados).
    assert deps.get_vector_store.cache_info().currsize == 0
    assert deps.get_embedding_service.cache_info().currsize == 0


async def test_close_services_never_builds_unused_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fechar não pode instanciar nada (criar cliente só para fechá-lo)."""
    created: list[str] = []

    def _boom() -> Any:
        created.append("built")
        raise AssertionError("não deveria construir serviços no shutdown")

    monkeypatch.setattr(deps, "VectorStore", _boom)
    monkeypatch.setattr(deps, "EmbeddingService", _boom)
    deps.get_vector_store.cache_clear()
    deps.get_embedding_service.cache_clear()

    await deps.close_services()

    assert created == []


async def test_lifespan_closes_services_on_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """O lifespan da app fecha os clientes ao sair (não só ao morrer o processo)."""
    from app import main as app_main

    calls: list[str] = []

    async def _fake_close() -> None:
        calls.append("closed")

    async def _noop_async() -> None:
        return None

    monkeypatch.setattr(app_main, "close_services", _fake_close)
    monkeypatch.setattr(app_main, "configure_langfuse_otel", lambda: None)

    async with app_main.lifespan(app_main.app):
        assert calls == []

    assert calls == ["closed"]
