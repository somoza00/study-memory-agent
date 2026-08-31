"""Orquestra o ciclo de memória: embedding -> vetor -> Qdrant e busca semântica.

Graceful degradation: se o Qdrant estiver indisponível, `store` devolve
`(id, persisted=False)` (o desfecho é exposto, não mascarado como sucesso) e
`recall` degrada para lista vazia. Nenhum dos dois levanta exceção por causa
do Qdrant. Falhas de embedding (ex.: OpenAI fora do ar) não são mascaradas:
sem vetor não há o que persistir ou buscar.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from qdrant_client.models import Record, ScoredPoint

from app.models.memory import MemoryMetadata, MemoryResult, StoredMemory
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)


class MemoryService:
    """Serviço de domínio para persistir e recuperar memórias de estudo."""

    def __init__(self, embedding_service: EmbeddingService, vector_store: VectorStore) -> None:
        self._embeddings = embedding_service
        self._store = vector_store

    async def store(self, text: str, metadata: MemoryMetadata) -> tuple[str, bool]:
        """Gera o embedding de `text`, persiste no Qdrant e retorna (id, persisted).

        `persisted` expõe o desfecho real ao chamador: se o Qdrant estiver
        indisponível, o id ainda é devolvido (sua geração não depende do
        Qdrant), mas `persisted` vira False — a perda silenciosa de memória
        deixa de ser mascarada como sucesso. O embedding nunca é mascarado:
        sem vetor não há o que persistir nem buscar.
        """
        vector = await self._embeddings.embed(text)
        memory_id = str(uuid4())
        payload = {"text": text, **metadata.model_dump(mode="json")}
        try:
            await self._store.upsert(memory_id, vector, payload)
        except Exception:
            logger.warning("Qdrant indisponível: memória %s NÃO foi persistida", memory_id)
            return memory_id, False
        return memory_id, True

    async def recall(self, query: str, limit: int, min_score: float) -> list[MemoryResult]:
        """Busca memórias semanticamente relacionadas a `query`.

        Retorna lista vazia se o Qdrant estiver indisponível.
        """
        vector = await self._embeddings.embed(query)
        try:
            points = await self._store.search(vector, limit, min_score)
        except Exception:
            logger.warning("Qdrant indisponível: recall retornando vazio")
            return []
        return [_to_memory_result(point) for point in points]

    async def list_topics(self) -> list[str]:
        """Lista os tópicos distintos das memórias existentes.

        Retorna lista vazia se o Qdrant estiver indisponível.
        """
        try:
            return await self._store.list_topics()
        except Exception:
            logger.warning("Qdrant indisponível: list_topics retornando vazio")
            return []

    async def list(self, topic: str | None = None, limit: int = 20) -> list[StoredMemory]:
        """Lista memórias persistidas, opcionalmente filtradas por `topic`.

        Retorna lista vazia se o Qdrant estiver indisponível.
        """
        try:
            records = await self._store.list(limit, topic)
        except Exception:
            logger.warning("Qdrant indisponível: list retornando vazio")
            return []
        return [_to_stored_memory(record) for record in records]

    async def delete(self, memory_id: str) -> None:
        """Remove uma memória pelo id.

        Não levanta exceção se o Qdrant estiver indisponível.
        """
        try:
            await self._store.delete(memory_id)
        except Exception:
            logger.warning("Qdrant indisponível: memória %s não foi removida", memory_id)


def _to_memory_result(point: ScoredPoint) -> MemoryResult:
    """Converte um `ScoredPoint` do Qdrant em `MemoryResult`."""
    payload = point.payload or {}
    text = str(payload.get("text", ""))
    metadata = MemoryMetadata.model_validate(payload)
    return MemoryResult(id=str(point.id), text=text, score=point.score, metadata=metadata)


def _to_stored_memory(record: Record) -> StoredMemory:
    """Converte um `Record` do Qdrant (scroll) em `StoredMemory`."""
    payload = record.payload or {}
    text = str(payload.get("text", ""))
    metadata = MemoryMetadata.model_validate(payload)
    return StoredMemory(id=str(record.id), text=text, metadata=metadata)
