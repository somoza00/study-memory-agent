"""Testes unitários do MemoryService, com embedding_service e vector_store mockados."""

from datetime import date
from unittest.mock import AsyncMock

from qdrant_client.models import Record, ScoredPoint

from app.models.memory import MemoryMetadata
from app.services.memory_service import MemoryService, RenameTopicStatus, UpdateMemoryStatus

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


async def test_store_truncates_very_long_text_before_embedding() -> None:
    service, embeddings, store = make_service()

    memory_id, persisted = await service.store("x" * 10_000, METADATA)

    embedded_text = embeddings.embed.await_args.args[0]
    assert len(embedded_text) <= 4000
    payload = store.upsert.await_args.args[2]
    assert len(payload["text"]) <= 4000
    assert isinstance(memory_id, str) and memory_id
    assert persisted is True


async def test_recall_clamps_limit_and_min_score() -> None:
    """A camada de serviço reclama limit/min_score fora da faixa."""
    service, _embeddings, store = make_service()
    store.search.return_value = []

    await service.recall("q", limit=500, min_score=-2.0)

    _vector, limit, min_score, _topic = store.search.await_args.args
    assert limit == 20
    assert min_score == 0.0


async def test_metadata_rejects_oversized_topic() -> None:
    """topic acima do limite vira erro de validação (não é aceito em silêncio)."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MemoryMetadata(
            topic="x" * 121,
            source="livro",
            date=date(2026, 8, 25),
            session_id="s1",
        )


async def test_metadata_rejects_blank_topic() -> None:
    """Metadata (topic/source/session_id) só com espaços é rejeitada (via do agente)."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MemoryMetadata(
            topic="  ", source="livro", date=date(2026, 8, 25), session_id="s1"
        )


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
    store.search.assert_awaited_once_with(VECTOR, 5, 0.5, None, session_id=None)
    assert len(results) == 1
    assert results[0].id == "abc"
    assert results[0].score == 0.87
    assert results[0].text == "dependency injection no FastAPI"
    assert results[0].metadata.topic == "fastapi"


async def test_recall_filters_by_topic() -> None:
    """`topic` é repassado para a busca vetorial (filtro de payload)."""
    service, _embeddings, store = make_service()
    store.search.return_value = []

    await service.recall("o que estudei sobre react?", limit=5, min_score=0.5, topic="react")

    assert store.search.await_args.args == (VECTOR, 5, 0.5, "react")


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
    store.list.assert_awaited_once_with(5, "fastapi", None)


async def test_list_filters_by_session() -> None:
    """`session_id` é repassado para a listagem (filtro de payload)."""
    service, _embeddings, store = make_service()
    store.list.return_value = []

    await service.list(topic="fastapi", limit=5, session_id="s9")

    assert store.list.await_args.args == (5, "fastapi", "s9")


async def test_list_degrades_to_empty() -> None:
    service, _embeddings, store = make_service()
    store.list.side_effect = ConnectionError("qdrant offline")

    assert await service.list() == []


async def test_get_delegates_and_converts() -> None:
    service, _embeddings, store = make_service()
    store.get.return_value = Record(
        id="abc",
        payload={
            "text": "sobre DI",
            "topic": "fastapi",
            "source": "livro",
            "date": "2026-08-25",
            "session_id": "s1",
        },
    )

    mem = await service.get("abc")

    assert mem is not None
    assert mem.id == "abc"
    assert mem.text == "sobre DI"
    assert mem.metadata.topic == "fastapi"
    store.get.assert_awaited_once_with("abc")


async def test_get_returns_none_when_missing() -> None:
    service, _embeddings, store = make_service()
    store.get.return_value = None

    assert await service.get("abc") is None


async def test_get_degrades_to_none_on_qdrant_offline() -> None:
    service, _embeddings, store = make_service()
    store.get.side_effect = ConnectionError("qdrant offline")

    assert await service.get("abc") is None


# --- Payload inválido (dado legado/gravado externamente) => degrada, nunca 500 ---


async def test_recall_degrades_to_empty_on_malformed_payload() -> None:
    """Payload sem session_id não estoura 500 no recall; retorna lista vazia."""
    service, _embeddings, store = make_service()
    store.search.return_value = [
        ScoredPoint(id="abc", version=1, score=0.9, payload={"text": "sobre DI"})
    ]

    results = await service.recall("o que sei?", limit=5, min_score=0.5)

    assert results == []


async def test_list_degrades_to_empty_on_malformed_payload() -> None:
    """Payload malformado na listagem degrada para [] (nunca 500)."""
    service, _embeddings, store = make_service()
    store.list.return_value = [Record(id="abc", payload={"text": "sobre DI"})]

    assert await service.list() == []


async def test_list_skips_corrupt_record_but_keeps_valid() -> None:
    """1 registro corrompido não esconde os válidos (skip por registro, não aborta o lote)."""
    service, _embeddings, store = make_service()
    store.list.return_value = [
        Record(id="ruim", payload={"text": "corrompido"}),
        Record(
            id="bom",
            payload={
                "text": "sobre DI",
                "topic": "fastapi",
                "source": "livro",
                "date": "2026-08-25",
                "session_id": "s1",
            },
        ),
    ]

    result = await service.list()

    assert [m.id for m in result] == ["bom"]


async def test_get_returns_none_on_malformed_payload() -> None:
    """Payload malformado no get degrada para None (nunca 500)."""
    service, _embeddings, store = make_service()
    store.get.return_value = Record(id="abc", payload={"text": "sobre DI"})

    assert await service.get("abc") is None


async def test_delete_delegates() -> None:
    service, _embeddings, store = make_service()

    await service.delete("abc")

    store.delete.assert_awaited_once_with("abc")


async def test_delete_session_delegates() -> None:
    service, _embeddings, store = make_service()

    await service.delete_session("sess-1")

    store.delete_by_session.assert_awaited_once_with("sess-1")


async def test_delete_session_degrades_on_qdrant_offline() -> None:
    service, _embeddings, store = make_service()
    store.delete_by_session.side_effect = ConnectionError("qdrant offline")

    # Não levanta exceção (graceful degradation).
    await service.delete_session("sess-1")
    assert True


# --- Grafia canônica de tópico (evita "FastAPI" + "fastapi" na sidebar) ---


async def test_canonical_topic_reuses_existing_spelling() -> None:
    service, _embeddings, store = make_service()
    store.list_topics.return_value = ["fastapi", "react"]

    assert await service.canonical_topic("FastAPI") == "fastapi"


async def test_canonical_topic_keeps_brand_new_topic_as_typed() -> None:
    service, _embeddings, store = make_service()
    store.list_topics.return_value = ["fastapi"]

    assert await service.canonical_topic("  SQL  ") == "SQL"


async def test_canonical_topic_ignores_whitespace_only_input() -> None:
    service, _embeddings, store = make_service()

    assert await service.canonical_topic("   ") == ""
    store.list_topics.assert_not_awaited()


async def test_canonical_topic_caches_the_topic_snapshot() -> None:
    """Sem cache, cada gravação custaria um scroll do Qdrant."""
    service, _embeddings, store = make_service()
    store.list_topics.return_value = ["fastapi"]

    await service.canonical_topic("FastAPI")
    await service.canonical_topic("FASTAPI")

    store.list_topics.assert_awaited_once()


async def test_store_invalidates_topic_cache() -> None:
    """Tópico novo gravado por outra via precisa aparecer na próxima canonicalização."""
    service, _embeddings, store = make_service()
    store.list_topics.return_value = ["fastapi"]

    await service.canonical_topic("fastapi")
    await service.store("texto", METADATA)
    await service.canonical_topic("fastapi")

    assert store.list_topics.await_count == 2


async def test_canonical_topic_survives_qdrant_offline() -> None:
    """Sem conseguir ler os tópicos, devolve o nome apenas normalizado."""
    service, _embeddings, store = make_service()
    store.list_topics.side_effect = ConnectionError("qdrant offline")

    assert await service.canonical_topic("  FastAPI  ") == "FastAPI"


# --- Renomear tópico ---


async def test_rename_topic_renames_and_reports_count() -> None:
    service, _embeddings, store = make_service()
    store.count_by_topic.return_value = 0  # nome novo ainda não existe
    store.rename_topic.return_value = 3

    result = await service.rename_topic("fastapi", "FastAPI DI")

    assert result.status is RenameTopicStatus.RENAMED
    assert result.updated == 3
    store.rename_topic.assert_awaited_once_with("fastapi", "FastAPI DI")


async def test_rename_topic_conflicts_with_existing_topic() -> None:
    """Nome já usado por outro tópico não funde em silêncio: vira CONFLICT."""
    service, _embeddings, store = make_service()
    store.count_by_topic.return_value = 2  # "react" já existe

    result = await service.rename_topic("fastapi", "react")

    assert result.status is RenameTopicStatus.CONFLICT
    store.rename_topic.assert_not_awaited()


async def test_rename_topic_not_found_when_source_missing() -> None:
    service, _embeddings, store = make_service()
    store.count_by_topic.return_value = 0
    store.rename_topic.return_value = 0

    result = await service.rename_topic("inexistente", "novo")

    assert result.status is RenameTopicStatus.NOT_FOUND


async def test_rename_topic_same_name_is_noop() -> None:
    """Renomear para o mesmo nome não escreve no Qdrant, mas confirma a contagem."""
    service, _embeddings, store = make_service()
    store.count_by_topic.return_value = 4

    result = await service.rename_topic("fastapi", "fastapi")

    assert result.status is RenameTopicStatus.RENAMED
    assert result.updated == 4
    store.rename_topic.assert_not_awaited()


async def test_rename_topic_same_name_unknown_topic_is_not_found() -> None:
    service, _embeddings, store = make_service()
    store.count_by_topic.return_value = 0

    result = await service.rename_topic("inexistente", "inexistente")

    assert result.status is RenameTopicStatus.NOT_FOUND


async def test_rename_topic_degrades_when_qdrant_offline() -> None:
    service, _embeddings, store = make_service()
    store.count_by_topic.side_effect = ConnectionError("qdrant offline")

    result = await service.rename_topic("fastapi", "novo")

    assert result.status is RenameTopicStatus.UNAVAILABLE


async def test_rename_topic_invalidates_topic_cache() -> None:
    """Renomear precisa esquecer a grafia antiga no cache (senão o tópico 'ressuscita')."""
    service, _embeddings, store = make_service()
    store.list_topics.return_value = ["fastapi"]
    store.count_by_topic.return_value = 0  # nome novo ainda não existe
    store.rename_topic.return_value = 2

    await service.canonical_topic("fastapi")  # popula o cache de grafia
    await service.rename_topic("fastapi", "FastAPI DI")
    await service.canonical_topic("fastapi")  # deve re-escanear (cache invalidado)

    assert store.list_topics.await_count == 2


# --- Editar memória (PATCH /api/memories/{id}) ---

_RECORD_PAYLOAD = {
    "text": "texto antigo",
    "topic": "fastapi",
    "source": "livro",
    "date": "2026-08-25",
    "session_id": "s1",
}


async def test_update_reembeds_and_preserves_metadata() -> None:
    """Re-embeda o texto novo no MESMO id, preservando a metadata."""
    service, embeddings, store = make_service()
    store.get.return_value = Record(id="abc", payload=_RECORD_PAYLOAD)

    result = await service.update("abc", "texto novo")

    assert result.status is UpdateMemoryStatus.UPDATED
    assert result.memory is not None
    assert result.memory.id == "abc"
    assert result.memory.text == "texto novo"
    assert result.memory.metadata.topic == "fastapi"
    embeddings.embed.assert_awaited_once_with("texto novo")
    called_id, called_vector, called_payload = store.upsert.await_args.args
    assert called_id == "abc"
    assert called_vector == VECTOR
    assert called_payload["text"] == "texto novo"
    assert called_payload["topic"] == "fastapi"  # metadata preservada
    assert called_payload["session_id"] == "s1"


async def test_update_not_found_when_missing() -> None:
    service, _embeddings, store = make_service()
    store.get.return_value = None

    result = await service.update("abc", "novo")

    assert result.status is UpdateMemoryStatus.NOT_FOUND
    store.upsert.assert_not_awaited()


async def test_update_unavailable_when_qdrant_offline_on_read() -> None:
    service, _embeddings, store = make_service()
    store.get.side_effect = ConnectionError("qdrant offline")

    result = await service.update("abc", "novo")

    assert result.status is UpdateMemoryStatus.UNAVAILABLE


async def test_update_unavailable_when_qdrant_offline_on_write() -> None:
    service, _embeddings, store = make_service()
    store.get.return_value = Record(id="abc", payload=_RECORD_PAYLOAD)
    store.upsert.side_effect = ConnectionError("qdrant offline")

    result = await service.update("abc", "novo")

    assert result.status is UpdateMemoryStatus.UNAVAILABLE


async def test_update_truncates_very_long_text() -> None:
    service, embeddings, store = make_service()
    store.get.return_value = Record(id="abc", payload=_RECORD_PAYLOAD)

    await service.update("abc", "x" * 10_000)

    assert len(embeddings.embed.await_args.args[0]) <= 4000
