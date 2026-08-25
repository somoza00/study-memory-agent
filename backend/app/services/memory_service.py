"""Orquestra o ciclo de memória: embedding -> vetor -> Qdrant e busca semântica.

Graceful degradation: se o Qdrant estiver indisponível, `store` loga um
warning (mas ainda devolve o id gerado, já que sua geração não depende do
Qdrant) e `recall` degrada para lista vazia. Nenhum dos dois levanta exceção
por causa do Qdrant. Falhas de embedding (ex.: OpenAI fora do ar) não são
mascaradas: sem vetor não há o que persistir ou buscar.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from qdrant_client.models import ScoredPoint

from app.models.memory import MemoryMetadata, MemoryResult
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)


class MemoryService:
    """Serviço de domínio para persistir e recuperar memórias de estudo."""

    def __init__(self, embedding_service: EmbeddingService, vector_store: VectorStore) -> None:
        self._embeddings = embedding_service
        self._store = vector_store

    async def store(self, text: str, metadata: MemoryMetadata) -> str:
        """Gera o embedding de `text`, persiste no Qdrant e retorna o id.

        Se o Qdrant estiver indisponível, loga um warning e ainda assim
        retorna o id gerado — a memória apenas não fica persistida.
        """
        vector = await self._embeddings.embed(text)
        memory_id = str(uuid4())
        payload = {"text": text, **metadata.model_dump(mode="json")}
        try:
            await self._store.upsert(memory_id, vector, payload)
        except Exception:
            logger.warning("Qdrant indisponível: memória %s não foi persistida", memory_id)
        return memory_id

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


def _to_memory_result(point: ScoredPoint) -> MemoryResult:
    """Converte um `ScoredPoint` do Qdrant em `MemoryResult`."""
    payload = point.payload or {}
    text = str(payload.get("text", ""))
    metadata = MemoryMetadata.model_validate(payload)
    return MemoryResult(id=str(point.id), text=text, score=point.score, metadata=metadata)
