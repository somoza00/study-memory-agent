"""Orquestra o ciclo de memória: embedding -> vetor -> Qdrant e busca semântica.

Graceful degradation: se o Qdrant estiver indisponível, `store` devolve
`(id, persisted=False)` (o desfecho é exposto, não mascarado como sucesso) e
`recall` degrada para lista vazia. Nenhum dos dois levanta exceção por causa
do Qdrant. Falhas de embedding (ex.: OpenAI fora do ar) não são mascaradas:
sem vetor não há o que persistir ou buscar.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from qdrant_client.models import Record, ScoredPoint

from app.models.memory import MemoryMetadata, MemoryResult, StoredMemory, TopicCount
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)

# Limite de caracteres do texto de uma memória: trunca ANTES do embedding para
# conter o custo (tokens) e evitar vetor diluído por um texto gigante.
_MAX_TEXT_CHARS = 4000

# Cache curto da lista de tópicos usada para canonicalizar a grafia: evita um
# scroll do Qdrant a cada gravação sem deixar a lista velha por muito tempo.
_TOPIC_CACHE_TTL = 30.0
_TOPIC_SCAN_LIMIT = 200


class RenameTopicStatus(StrEnum):
    """Desfecho de um rename de tópico (o router traduz para o status HTTP)."""

    RENAMED = "renamed"
    NOT_FOUND = "not_found"  # tópico de origem não existe
    CONFLICT = "conflict"  # já existe um tópico com o nome desejado
    UNAVAILABLE = "unavailable"  # armazenamento vetorial fora do ar


@dataclass(frozen=True)
class RenameTopicResult:
    """Resultado do `rename_topic`: desfecho + quantas memórias mudaram."""

    status: RenameTopicStatus
    updated: int = 0


class UpdateMemoryStatus(StrEnum):
    """Desfecho de um update de memória (o router traduz para o status HTTP)."""

    UPDATED = "updated"
    NOT_FOUND = "not_found"  # a memória não existe
    UNAVAILABLE = "unavailable"  # armazenamento vetorial fora do ar


@dataclass(frozen=True)
class UpdateMemoryResult:
    """Resultado do `update`: desfecho + a memória já com o texto novo."""

    status: UpdateMemoryStatus
    memory: StoredMemory | None = None


class MemoryService:
    """Serviço de domínio para persistir e recuperar memórias de estudo."""

    def __init__(self, embedding_service: EmbeddingService, vector_store: VectorStore) -> None:
        self._embeddings = embedding_service
        self._store = vector_store
        # Snapshot (timestamp, {casefold: grafia}) dos tópicos existentes.
        self._topic_spellings: tuple[float, dict[str, str]] | None = None

    async def store(self, text: str, metadata: MemoryMetadata) -> tuple[str, bool]:
        """Gera o embedding de `text`, persiste no Qdrant e retorna (id, persisted).

        `persisted` expõe o desfecho real ao chamador: se o Qdrant estiver
        indisponível, o id ainda é devolvido (sua geração não depende do
        Qdrant), mas `persisted` vira False — a perda silenciosa de memória
        deixa de ser mascarada como sucesso. O embedding nunca é mascarado:
        sem vetor não há o que persistir nem buscar.
        """
        text = text[:_MAX_TEXT_CHARS]  # contém custo de embedding / vetor diluído
        vector = await self._embeddings.embed(text)
        memory_id = str(uuid4())
        payload = {"text": text, **metadata.model_dump(mode="json")}
        try:
            await self._store.upsert(memory_id, vector, payload)
        except Exception:
            logger.warning("Qdrant indisponível: memória %s NÃO foi persistida", memory_id)
            return memory_id, False
        self._invalidate_topic_cache()  # o tópico pode ser novo
        return memory_id, True

    async def recall(
        self,
        query: str,
        limit: int,
        min_score: float,
        topic: str | None = None,
        session_id: str | None = None,
    ) -> list[MemoryResult]:
        """Busca memórias relacionadas a `query`, filtradas por `topic` e/ou `session_id`.

        Retorna lista vazia se o Qdrant estiver indisponível.
        """
        # Defesa na camada de serviço (além do clamp na tool do agente):
        # limita o volume buscado e mantém o score_threshold em [0,1].
        limit = max(1, min(limit, 20))
        min_score = max(0.0, min(min_score, 1.0))
        vector = await self._embeddings.embed(query)
        try:
            points = await self._store.search(
                vector, limit, min_score, topic, session_id=session_id
            )
            out: list[MemoryResult] = []
            for point in points:
                try:
                    out.append(_to_memory_result(point))
                except Exception:
                    logger.warning("memória %s ignorada no recall: payload malformado", point.id)
            return out
        except Exception:
            logger.warning("Qdrant indisponível ou payload inválido: recall retornando vazio")
            return []

    async def canonical_topic(self, topic: str) -> str:
        """Resolve a grafia canônica de `topic` entre os tópicos já existentes.

        O agente escolhe a string do tópico livremente, então "FastAPI" e
        "fastapi" viravam dois tópicos separados na sidebar (mesmo assunto
        duplicado). Aqui reaproveitamos a grafia de um tópico existente quando a
        diferença é só caixa/espaços; o tópico realmente novo passa como veio.
        Devolve o nome normalizado (trim) se o armazenamento estiver fora.
        """
        cleaned = topic.strip()
        if not cleaned:
            return cleaned
        key = cleaned.casefold()
        now = time.monotonic()
        cached = self._topic_spellings
        if cached is None or now - cached[0] > _TOPIC_CACHE_TTL:
            try:
                topics = await self._store.list_topics(_TOPIC_SCAN_LIMIT)
            except Exception:
                logger.warning("Qdrant indisponível: não foi possível canonicalizar o tópico")
                return cleaned
            cached = (now, {t.casefold(): t for t in topics})
            self._topic_spellings = cached
        return cached[1].get(key, cleaned)

    def _invalidate_topic_cache(self) -> None:
        """Descarta o snapshot de tópicos (após gravar/renomear/remover)."""
        self._topic_spellings = None

    async def rename_topic(self, topic: str, name: str) -> RenameTopicResult:
        """Renomeia um tópico em todas as memórias que o usam.

        Regras (o router espelha cada desfecho num status HTTP):
        - tópico de origem inexistente → `NOT_FOUND` (não inventa tópico vazio);
        - nome já usado por outro tópico → `CONFLICT`, em vez de fundir dois
          tópicos em silêncio (fundir é intenção diferente de renomear);
        - Qdrant indisponível → `UNAVAILABLE` (503, como `delete`/`delete_session`).
        """
        try:
            # Renomear para o próprio nome é no-op no Qdrant; só confirma que o
            # tópico existe (e devolve a contagem real, não um write inútil).
            if topic == name:
                count = await self._store.count_by_topic(topic)
                status = RenameTopicStatus.RENAMED if count else RenameTopicStatus.NOT_FOUND
                return RenameTopicResult(status=status, updated=count)
            if await self._store.count_by_topic(name):
                return RenameTopicResult(status=RenameTopicStatus.CONFLICT)
            updated = await self._store.rename_topic(topic, name)
        except Exception:
            logger.warning("Qdrant indisponível: tópico %s não foi renomeado", topic)
            return RenameTopicResult(status=RenameTopicStatus.UNAVAILABLE)
        if updated == 0:
            return RenameTopicResult(status=RenameTopicStatus.NOT_FOUND)
        return RenameTopicResult(status=RenameTopicStatus.RENAMED, updated=updated)

    async def list_topics(self, limit: int = 50) -> list[str]:
        """Lista tópicos distintos (até `limit`); lista vazia se Qdrant fora."""
        try:
            return await self._store.list_topics(limit)
        except Exception:
            logger.warning("Qdrant indisponível: list_topics retornando vazio")
            return []

    async def topic_counts(self, limit: int = 50) -> list[TopicCount]:
        """Lista tópicos distintos com a contagem de memórias de cada um.

        Lista vazia se o Qdrant estiver indisponível (graceful degradation).
        """
        try:
            topics = await self._store.list_topics(limit)
            counts: list[TopicCount] = []
            for topic in topics:
                counts.append(
                    TopicCount(topic=topic, count=await self._store.count_by_topic(topic))
                )
            return counts
        except Exception:
            logger.warning("Qdrant indisponível: topic_counts retornando vazio")
            return []

    async def list(
        self,
        topic: str | None = None,
        limit: int = 20,
        session_id: str | None = None,
    ) -> list[StoredMemory]:
        """Lista memórias persistidas, opcionalmente filtradas por `topic` e `session_id`.

        Retorna lista vazia se o Qdrant estiver indisponível.
        """
        try:
            records = await self._store.list(limit, topic, session_id)
            out: list[StoredMemory] = []
            for record in records:
                try:
                    out.append(_to_stored_memory(record))
                except Exception:
                    logger.warning("memória %s ignorada: payload malformado", record.id)
            return out
        except Exception:
            logger.warning("Qdrant indisponível ou payload inválido: list retornando vazio")
            return []

    async def delete(self, memory_id: str) -> bool:
        """Remove uma memória pelo id.

        Retorna `True` se o armazenamento confirmou a remoção; `False` se o
        Qdrant estava indisponível (a remoção pode não ter ocorrido — o router
        espelha o desfecho em 503, como o `store` faz `(id, persisted)`).
        """
        try:
            await self._store.delete(memory_id)
        except Exception:
            logger.warning("Qdrant indisponível: memória %s não foi removida", memory_id)
            return False
        self._invalidate_topic_cache()  # o tópico pode ter ficado vazio
        return True

    async def delete_session(self, session_id: str) -> bool:
        """Remove todas as memórias de uma sessão de conversa.

        Retorna `True` se o armazenamento confirmou a remoção; `False` se o
        Qdrant estava indisponível (o router responde 503 nesse caso).
        """
        try:
            await self._store.delete_by_session(session_id)
        except Exception:
            logger.warning("Qdrant indisponível: delete_session (%s) não executado", session_id)
            return False
        self._invalidate_topic_cache()
        return True

    async def get(self, memory_id: str) -> StoredMemory | None:
        """Retorna uma memória pelo id, ou `None` se não existir.

        Retorna `None` também se o Qdrant estiver indisponível (graceful).
        """
        try:
            record = await self._store.get(memory_id)
            return _to_stored_memory(record) if record else None
        except Exception:
            logger.warning("Qdrant indisponível ou payload inválido: get retornando None")
            return None

    async def update(self, memory_id: str, text: str) -> UpdateMemoryResult:
        """Atualiza o texto de uma memória, re-embedando no MESMO id.

        Preserva a metadata (topic/source/date/session_id) e o id: só o texto e o
        vetor mudam — editar o texto não deve reclassificar nem "mover" a memória.
        Desfechos: `NOT_FOUND` se a memória não existe, `UNAVAILABLE` se o Qdrant
        estiver fora (o router espelha em 503, como `delete`). Uma falha de
        embedding NÃO é mascarada — propaga, porque sem vetor não há update (mesma
        regra do `store`).
        """
        text = text[:_MAX_TEXT_CHARS]
        try:
            record = await self._store.get(memory_id)
        except Exception:
            logger.warning("Qdrant indisponível: memória %s não foi atualizada", memory_id)
            return UpdateMemoryResult(status=UpdateMemoryStatus.UNAVAILABLE)
        if record is None:
            return UpdateMemoryResult(status=UpdateMemoryStatus.NOT_FOUND)
        metadata = MemoryMetadata.model_validate(record.payload or {})
        vector = await self._embeddings.embed(text)
        payload = {"text": text, **metadata.model_dump(mode="json")}
        try:
            await self._store.upsert(memory_id, vector, payload)
        except Exception:
            logger.warning("Qdrant indisponível: memória %s NÃO foi atualizada", memory_id)
            return UpdateMemoryResult(status=UpdateMemoryStatus.UNAVAILABLE)
        return UpdateMemoryResult(
            status=UpdateMemoryStatus.UPDATED,
            memory=StoredMemory(id=memory_id, text=text, metadata=metadata),
        )


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
