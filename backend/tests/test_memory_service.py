"""Testes unitários do MemoryService, com embedding_service e vector_store mockados."""

from datetime import date
from unittest.mock import AsyncMock

from qdrant_client.models import Record, ScoredPoint

from app.models.memory import MemoryMetadata
from app.services.memory_service import MemoryService

METADATA = MemoryMetadata(topic="fastapi", source="livro", date=date(2026, 8, 25), session_id="s1")
VECTOR = [0.1, 0.2, 0.3]


def make_service() -> tuple[MemoryService, AsyncMock, AsyncMock]:
    embeddings = AsyncMock()
    embeddings.embed.return_value = VECTOR
    store = AsyncMock()
    service = MemoryService(embedding_service=embeddings, vector_store=store)
    return service, embeddings, store


async def test_store_embeds_and_upserts() -> None:
    service, embeddings, store = make_service()

    memory_id, persisted = await service.store("dependency injection no FastAPI", METADATA)

    embeddings.embed.assert_awaited_once_with("dependency injection no FastAPI")
    store.upsert.assert_awaited_once()
    assert persisted is True
    called_id, called_vector, called_payload = store.upsert.await_args.args
    assert called_id == memory_id
    assert called_vector == VECTOR
    assert called_payload["text"] == "dependency injection no FastAPI"
    assert called_payload["topic"] == "fastapi"
    assert called_payload["session_id"] == "s1"


async def test_store_reports_not_persisted_when_qdrant_offline() -> None:
    service, _embeddings, store = make_service()
    store.upsert.side_effect = ConnectionError("qdrant offline")

    memory_id, persisted = await service.store("texto qualquer", METADATA)

    assert isinstance(memory_id, str) and memory_id
    assert persisted is False


async def test_recall_returns_scored_memories() -> None:
    service, embeddings, store = make_service()
    store.search.return_value = [
        ScoredPoint(
            id="abc",
            version=1,
            score=0.87,
            payload={
                "text": "dependency injection no FastAPI",
                "topic": "fastapi",
                "source": "livro",
                "date": "2026-08-25",
                "session_id": "s1",
            },
        )
    ]

    results = await service.recall("como funciona DI no FastAPI?", limit=5, min_score=0.5)

    embeddings.embed.assert_awaited_once_with("como funciona DI no FastAPI?")
    store.search.assert_awaited_once_with(VECTOR, 5, 0.5)
    assert len(results) == 1
    assert results[0].id == "abc"
    assert results[0].score == 0.87
    assert results[0].text == "dependency injection no FastAPI"
    assert results[0].metadata.topic == "fastapi"


async def test_recall_degrades_to_empty_list_if_qdrant_offline() -> None:
    service, _embeddings, store = make_service()
    store.search.side_effect = ConnectionError("qdrant offline")

    results = await service.recall("qualquer coisa", limit=5, min_score=0.5)

    assert results == []


async def test_recall_empty_when_no_matches() -> None:
    service, _embeddings, store = make_service()
    store.search.return_value = []

    results = await service.recall("nada relacionado", limit=5, min_score=0.9)

    assert results == []


async def test_list_topics_delegates() -> None:
    service, _embeddings, store = make_service()
    store.list_topics.return_value = ["react", "fastapi"]

    topics = await service.list_topics()

    assert topics == ["react", "fastapi"]
    store.list_topics.assert_awaited_once()


async def test_list_topics_degrades_to_empty() -> None:
    service, _embeddings, store = make_service()
    store.list_topics.side_effect = ConnectionError("qdrant offline")

    assert await service.list_topics() == []


async def test_list_delegates_and_converts_records() -> None:
    service, _embeddings, store = make_service()
    store.list.return_value = [
        Record(
            id="abc",
            payload={
                "text": "sobre DI",
                "topic": "fastapi",
                "source": "livro",
                "date": "2026-08-25",
                "session_id": "s1",
            },
        )
    ]

    results = await service.list(topic="fastapi", limit=5)

    assert len(results) == 1
    assert results[0].id == "abc"
    assert results[0].metadata.topic == "fastapi"
    assert results[0].text == "sobre DI"
    store.list.assert_awaited_once_with(5, "fastapi")


async def test_list_degrades_to_empty() -> None:
    service, _embeddings, store = make_service()
    store.list.side_effect = ConnectionError("qdrant offline")

    assert await service.list() == []


async def test_delete_delegates() -> None:
    service, _embeddings, store = make_service()

    await service.delete("abc")

    store.delete.assert_awaited_once_with("abc")
