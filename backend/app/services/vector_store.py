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
    FilterSelector,
    MatchValue,
    PointIdsList,
    PointStruct,
    Record,
    ScoredPoint,
    VectorParams,
)

from app.core.config import Settings, settings


class VectorStore:
    """Operações de baixo nível sobre uma collection Qdrant."""

    def __init__(
        self,
        client: AsyncQdrantClient | None = None,
        config: Settings = settings,
        vector_size: int | None = None,
    ) -> None:
        self._client = client or AsyncQdrantClient(host=config.qdrant_host, port=config.qdrant_port)
        self._collection = config.qdrant_collection
        # Dimensão vem da config (`EMBEDDING_DIM`): precisa casar com o modelo de
        # embedding escolhido, que pode ser local (384) ou OpenAI (1536).
        self._vector_size = config.embedding_dim if vector_size is None else vector_size
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

    def _invalidate_collection(self) -> None:
        """Zera a flag de collection pronta: a próxima chamada re-verifica e
        recria a collection caso ela tenha sido apagada externamente (wipe/reset
        do Qdrant) ou esteja em indisponibilidade transitória. Self-healing —
        custo só no caminho de erro, não em toda op OK."""
        self._collection_ready = False

    async def upsert(self, id: str, vector: list[float], payload: dict[str, object]) -> None:
        """Insere ou atualiza um ponto na collection."""
        try:
            await self._ensure_collection()
            await self._client.upsert(
                collection_name=self._collection,
                points=[PointStruct(id=id, vector=vector, payload=payload)],
            )
        except Exception:
            self._invalidate_collection()
            raise

    async def search(
        self,
        vector: list[float],
        limit: int,
        min_score: float,
        topic: str | None = None,
        session_id: str | None = None,
    ) -> list[ScoredPoint]:
        """Retorna os pontos mais similares a `vector`, filtrados por `topic` e/ou `session_id`."""
        await self._ensure_collection()
        conditions: list[FieldCondition] = []
        if topic is not None:
            conditions.append(FieldCondition(key="topic", match=MatchValue(value=topic)))
        if session_id is not None:
            conditions.append(
                FieldCondition(key="session_id", match=MatchValue(value=session_id))
            )
        query_filter: Filter | None = (
            Filter(must=conditions) if conditions else None  # type: ignore[arg-type]
        )
        try:
            await self._ensure_collection()
            response = await self._client.query_points(
                collection_name=self._collection,
                query=vector,
                query_filter=query_filter,
                limit=limit,
                score_threshold=min_score,
            )
        except Exception:
            self._invalidate_collection()
            raise
        return response.points

    async def delete(self, id: str) -> None:
        """Remove um ponto pelo id."""
        try:
            await self._ensure_collection()
            await self._client.delete(
                collection_name=self._collection,
                points_selector=PointIdsList(points=[id]),
            )
        except Exception:
            self._invalidate_collection()
            raise

    async def get(self, id: str) -> Record | None:
        """Retorna um ponto pelo id, ou `None` se não existir."""
        try:
            await self._ensure_collection()
            points = await self._client.retrieve(
                collection_name=self._collection,
                ids=[id],
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            self._invalidate_collection()
            raise
        return points[0] if points else None

    async def delete_by_session(self, session_id: str) -> None:
        """Remove todos os pontos cujo payload tem `session_id` (filtro)."""
        try:
            await self._ensure_collection()
            await self._client.delete(
                collection_name=self._collection,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))]
                    )
                ),
            )
        except Exception:
            self._invalidate_collection()
            raise

    async def list_topics(self, limit: int = 50) -> list[str]:
        """Retorna até `limit` tópicos distintos presentes na collection.

        Para o scroll assim que o limite é atingido (coleção pode ser grande;
        antes fazia scan da coleção inteira, resposta/scan runaway).
        """
        topics: set[str] = set()
        offset: types.PointId | None = None
        try:
            await self._ensure_collection()
            while len(topics) < limit:
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
        except Exception:
            self._invalidate_collection()
            raise
        return sorted(topics)[:limit]

    async def count_by_topic(self, topic: str) -> int:
        """Conta as memórias persistidas de um tópico (exato). Self-heal em falha."""
        try:
            await self._ensure_collection()
            result = await self._client.count(
                collection_name=self._collection,
                count_filter=Filter(
                    must=[FieldCondition(key="topic", match=MatchValue(value=topic))]
                ),
                exact=True,
            )
        except Exception:
            self._invalidate_collection()
            raise
        return int(result.count)

    async def rename_topic(self, topic: str, name: str) -> int:
        """Renomeia `topic` para `name` em todos os pontos que o usam.

        Devolve quantas memórias foram renomeadas (0 se o tópico não existe).
        `set_payload` por filtro é uma única chamada no servidor: não há
        read-modify-write ponto a ponto (e o vetor não é tocado — só o payload).
        """
        try:
            await self._ensure_collection()
            total = await self.count_by_topic(topic)
            if total == 0:
                return 0
            await self._client.set_payload(
                collection_name=self._collection,
                payload={"topic": name},
                points=FilterSelector(
                    filter=Filter(
                        must=[FieldCondition(key="topic", match=MatchValue(value=topic))]
                    )
                ),
            )
        except Exception:
            self._invalidate_collection()
            raise
        return total

    async def list(
        self, limit: int, topic: str | None = None, session_id: str | None = None
    ) -> list[Record]:
        """Lista memórias, filtradas por `topic` e `session_id`, limitadas a `limit`."""
        conditions = []
        if topic is not None:
            conditions.append(FieldCondition(key="topic", match=MatchValue(value=topic)))
        if session_id is not None:
            conditions.append(
                FieldCondition(key="session_id", match=MatchValue(value=session_id))
            )
        # `Filter.must` é tipado como lista invariante no qdrant-client; o literal
        # inline funciona, mas construção incremental exige ignore (quirk do cliente).
        scroll_filter: Filter | None = (
            Filter(must=conditions) if conditions else None  # type: ignore[arg-type]
        )
        try:
            await self._ensure_collection()
            records, _next_page = await self._client.scroll(
                collection_name=self._collection,
                scroll_filter=scroll_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            self._invalidate_collection()
            raise
        return records

    async def ping(self) -> bool:
        """Retorna `True` se o Qdrant responder; `False` em qualquer erro (não levanta)."""
        try:
            await self._client.get_collections()
            return True
        except Exception:
            return False
