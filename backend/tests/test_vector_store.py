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

    def __init__(
        self,
        hits: list[Any] | None = None,
        error: Exception | None = None,
        records: list[Any] | None = None,
        scroll_error: Exception | None = None,
    ) -> None:
        self.hits = hits or []
        self.error = error
        self.facet_calls: list[dict[str, Any]] = []
        self.indexed_fields: list[str] = []
        self.exists = True
        # Respostas do caminho de fallback (`scroll`): cada elemento é um Record
        # com `payload`.
        self.records = records or []
        self.scroll_error = scroll_error
        self.scroll_calls: list[dict[str, Any]] = []

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

    async def scroll(self, **kwargs: Any) -> tuple[list[Any], None]:
        self.scroll_calls.append(kwargs)
        if self.scroll_error is not None:
            raise self.scroll_error
        return self.records, None


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


async def test_list_topics_uses_one_facet_call_instead_of_a_full_scroll() -> None:
    """`list_topics` resolve a lista num `facet` (índice), sem varrer a collection.

    O scroll anterior lia a collection INTEIRA quando havia menos tópicos
    distintos que `limit` (3 tópicos em 10 mil memórias = 10 mil pontos lidos) —
    e `canonical_topic` invalida o cache a cada gravação, então cada store pagava
    esse scan.
    """
    client = _StubQdrant(
        hits=[
            SimpleNamespace(value="python", count=3),
            SimpleNamespace(value="fastapi", count=7),
        ],
        records=[SimpleNamespace(payload={"topic": "nao-deveria-ser-lido"})],
    )
    store = make_store(client)

    assert await store.list_topics(50) == ["fastapi", "python"]
    assert client.facet_calls == [
        {"collection_name": store._collection, "key": "topic", "limit": 50, "exact": True}
    ]
    assert client.scroll_calls == []  # nenhum ponto lido da collection


async def test_list_sessions_uses_facet_on_session_id() -> None:
    client = _StubQdrant(hits=[SimpleNamespace(value="sess-2", count=1)])
    store = make_store(client)

    assert await store.list_sessions(10) == ["sess-2"]
    assert client.facet_calls[0]["key"] == "session_id"
    assert client.facet_calls[0]["limit"] == 10


async def test_list_topics_falls_back_to_scroll_without_facet() -> None:
    """Servidor/Qdrant anterior ao 1.12 (sem `facet`) continua funcionando."""
    client = _StubQdrant(
        error=AttributeError("facet"),
        records=[
            SimpleNamespace(payload={"topic": "python"}),
            SimpleNamespace(payload={"topic": "fastapi"}),
            SimpleNamespace(payload={"topic": "python"}),
            SimpleNamespace(payload={}),
        ],
    )
    store = make_store(client)

    assert await store.list_topics(50) == ["fastapi", "python"]
    assert len(client.scroll_calls) == 1


async def test_list_sessions_fallback_respects_limit_and_dedupes() -> None:
    client = _StubQdrant(
        error=AttributeError("facet"),
        records=[
            SimpleNamespace(payload={"session_id": "sess-1"}),
            SimpleNamespace(payload={"session_id": "sess-1"}),
            SimpleNamespace(payload={"session_id": "sess-2"}),
        ],
    )
    store = make_store(client)

    assert await store.list_sessions(1) == ["sess-1"]
