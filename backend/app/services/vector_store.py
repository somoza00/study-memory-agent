"""Wrapper assíncrono sobre o qdrant-client.

Cria a collection sob demanda (idempotente) e expõe upsert/search/delete.
A busca usa `query_points`, a API não-deprecada de similaridade do cliente
Qdrant. Este módulo não implementa graceful degradation — as exceções do
cliente propagam; quem decide degradar é o `memory_service`, que orquestra
esta camada junto com os embeddings.
"""

from __future__ import annotations

from qdrant_client import AsyncQdrantClient
from qdrant_client.conversions import common_types as types
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
    Record,
    ScoredPoint,
    VectorParams,
)

from app.core.config import Settings, settings

EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small


class VectorStore:
    """Operações de baixo nível sobre uma collection Qdrant."""

    def __init__(
        self,
        client: AsyncQdrantClient | None = None,
        config: Settings = settings,
        vector_size: int = EMBEDDING_DIMENSIONS,
    ) -> None:
        self._client = client or AsyncQdrantClient(host=config.qdrant_host, port=config.qdrant_port)
        self._collection = config.qdrant_collection
        self._vector_size = vector_size
        self._collection_ready = False

    async def _ensure_collection(self) -> None:
        """Cria a collection se ela ainda não existir."""
        if self._collection_ready:
            return
        if not await self._client.collection_exists(self._collection):
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=self._vector_size, distance=Distance.COSINE),
            )
        self._collection_ready = True

    async def upsert(self, id: str, vector: list[float], payload: dict[str, object]) -> None:
        """Insere ou atualiza um ponto na collection."""
        await self._ensure_collection()
        await self._client.upsert(
            collection_name=self._collection,
            points=[PointStruct(id=id, vector=vector, payload=payload)],
        )

    async def search(self, vector: list[float], limit: int, min_score: float) -> list[ScoredPoint]:
        """Retorna os pontos mais similares a `vector`, ordenados por score."""
        await self._ensure_collection()
        response = await self._client.query_points(
            collection_name=self._collection,
            query=vector,
            limit=limit,
            score_threshold=min_score,
        )
        return response.points

    async def delete(self, id: str) -> None:
        """Remove um ponto pelo id."""
        await self._ensure_collection()
        await self._client.delete(
            collection_name=self._collection,
            points_selector=PointIdsList(points=[id]),
        )

    async def list_topics(self) -> list[str]:
        """Retorna os `topic` distintos presentes na collection."""
        topics: set[str] = set()
        offset: types.PointId | None = None
        while True:
            records, next_page = await self._client.scroll(
                collection_name=self._collection,
                scroll_filter=None,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for record in records:
                topic = (record.payload or {}).get("topic")
                if topic:
                    topics.add(str(topic))
            if next_page is None or not records:
                break
            offset = next_page
        return sorted(topics)

    async def list(self, limit: int, topic: str | None = None) -> list[Record]:
        """Lista memórias, opcionalmente filtradas por `topic`, limitadas a `limit`."""
        await self._ensure_collection()
        scroll_filter: Filter | None = None
        if topic is not None:
            scroll_filter = Filter(
                must=[FieldCondition(key="topic", match=MatchValue(value=topic))]
            )
        records, _next_page = await self._client.scroll(
            collection_name=self._collection,
            scroll_filter=scroll_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return records

    async def ping(self) -> bool:
        """Retorna `True` se o Qdrant responder; `False` em qualquer erro (não levanta)."""
        try:
            await self._client.get_collections()
            return True
        except Exception:
            return False
