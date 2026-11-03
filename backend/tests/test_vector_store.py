"""Testes do `VectorStore.topic_counts`: uma chamada `facet` no lugar do N+1.

A sidebar (`GET /api/topics/counts`) fazia 1 scroll + um `count` por tópico —
até 201 round trips por requisição. O `facet` do Qdrant devolve valor+contagem
exata de um campo do payload numa chamada só; estes testes fixam o contrato da
chamada (chave, limite, exatidão) sem precisar de um Qdrant no ar.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.services.vector_store import VectorStore


class _StubQdrant:
    """Cliente Qdrant mínimo: registra a chamada de `facet` e devolve o que o teste mandar."""

    def __init__(self, hits: list[Any] | None = None, error: Exception | None = None) -> None:
        self.hits = hits or []
        self.error = error
        self.facet_calls: list[dict[str, Any]] = []
        self.indexed_fields: list[str] = []
        self.exists = True

    async def collection_exists(self, _collection: str) -> bool:
        return self.exists

    async def create_collection(self, **_kwargs: Any) -> None:
        return None

    async def create_payload_index(self, **kwargs: Any) -> None:
        self.indexed_fields.append(str(kwargs["field_name"]))

    async def facet(self, **kwargs: Any) -> SimpleNamespace:
        self.facet_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(hits=self.hits)


def make_store(client: _StubQdrant) -> VectorStore:
    return VectorStore(client=client, vector_size=3)  # type: ignore[arg-type]


async def test_topic_counts_maps_facet_hits_and_sorts_by_topic() -> None:
    client = _StubQdrant(
        hits=[
            SimpleNamespace(value="python", count=3),
            SimpleNamespace(value="fastapi", count=7),
        ]
    )
    store = make_store(client)

    assert await store.topic_counts(50) == [("fastapi", 7), ("python", 3)]
    # Uma única chamada, com a chave de payload certa e contagem exata (a
    # aproximada poderia subestimar tópicos grandes e enganar a sidebar).
    assert client.facet_calls == [
        {"collection_name": store._collection, "key": "topic", "limit": 50, "exact": True}
    ]


async def test_topic_counts_respects_limit_argument() -> None:
    client = _StubQdrant(hits=[SimpleNamespace(value="python", count=1)])
    store = make_store(client)

    await store.topic_counts(5)

    assert client.facet_calls[0]["limit"] == 5


async def test_ensure_collection_creates_payload_indexes_once() -> None:
    """Os filtros e o `facet` exigem índice de payload: criados na primeira operação.

    Qdrant recusa `facet` sem índice ("No appropriate index for faceting") e,
    sem índice, cada filtro por tópico/sessão varre a collection inteira.
    """
    client = _StubQdrant(hits=[])
    store = make_store(client)

    await store.topic_counts()
    await store.topic_counts()

    assert client.indexed_fields == ["topic", "session_id", "source"]


async def test_topic_counts_returns_empty_when_collection_has_no_topics() -> None:
    store = make_store(_StubQdrant(hits=[]))

    assert await store.topic_counts() == []


async def test_topic_counts_propagates_errors_and_allows_retry() -> None:
    """Falha do Qdrant propaga (o serviço decide degradar) e a próxima chamada
    re-verifica a collection — mesmo self-heal dos outros métodos."""
    client = _StubQdrant(error=ConnectionError("qdrant offline"))
    store = make_store(client)

    try:
        await store.topic_counts()
    except ConnectionError:
        pass
    else:  # pragma: no cover - só falha se o contrato mudar
        raise AssertionError("topic_counts deveria propagar o erro do Qdrant")

    assert store._collection_ready is False
