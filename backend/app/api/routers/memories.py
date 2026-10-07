"""Router de memórias: listagem, tópicos e remoção.

Expõe:
- `GET    /api/memories?topic=&limit=`   → lista memórias (filtro opcional por tópico)
- `GET    /api/topics`                    → tópicos distintos existentes
- `PATCH  /api/topics`                    → renomeia um tópico (renomear da sidebar)
- `DELETE /api/memories/{id}`            → remove uma memória pelo id
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from openai import OpenAIError

from app.api.deps import get_memory_service, get_vector_store
from app.models.memory import (
    MemoryCreate,
    MemoryCreated,
    MemoryMetadata,
    MemoryResult,
    StoredMemory,
    TopicCount,
    TopicRename,
    TopicRenamed,
)
from app.services.memory_service import MemoryService, RenameTopicStatus
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["memories"])


@router.post("/memories", status_code=status.HTTP_201_CREATED, response_model=MemoryCreated)
async def create_memory(
    payload: MemoryCreate,
    memory: MemoryService = Depends(get_memory_service),
) -> MemoryCreated:
    """Cria (armazena) uma memória manualmente, além de via agente."""
    metadata = MemoryMetadata(
        topic=payload.topic,
        source=payload.source,
        date=date.today(),
        session_id=payload.session_id,
    )
    try:
        memory_id, persisted = await memory.store(payload.text, metadata)
    except OpenAIError as exc:
        # Espelha o /api/chat: falha de embedding (OpenAI) vira 502, não 500 cru
        # (regra do AGENTS.md: nunca 500).
        raise HTTPException(
            status_code=502, detail=f"Falha ao gerar embedding: {exc}"
        ) from exc
    except Exception as exc:
        # Espelha o /api/chat: erro não-OpenAI também vira 502 estruturado,
        # nunca 500 cru (regra do AGENTS.md).
        logger.exception("POST /api/memories falhou com erro não-OpenAI")
        raise HTTPException(status_code=502, detail=f"Erro interno: {exc}") from exc
    return MemoryCreated(id=memory_id, persisted=persisted, metadata=metadata)


@router.get("/memories", response_model=list[StoredMemory])
async def list_memories(
    topic: str | None = Query(
        default=None, max_length=120, description="Filtra memórias por tópico."
    ),
    session_id: str | None = Query(
        default=None, max_length=200, description="Filtra memórias por sessão de conversa."
    ),
    limit: int = Query(default=20, ge=1, le=100, description="Quantidade máxima de itens."),
    memory: MemoryService = Depends(get_memory_service),
) -> list[StoredMemory]:
    """Lista memórias persistidas, opcionalmente filtradas por `topic` e/ou `session_id`."""
    return await memory.list(topic=topic, limit=limit, session_id=session_id)


@router.get("/memories/search", response_model=list[MemoryResult])
async def search_memories(
    q: str = Query(..., min_length=1, max_length=2000, description="Consulta textual."),
    limit: int = Query(default=10, ge=1, le=50, description="Máximo de memórias retornadas."),
    min_score: float = Query(default=0.7, ge=0.0, le=1.0, description="Similaridade mínima (0-1)."),
    topic: str | None = Query(default=None, max_length=120, description="Filtra por tópico."),
    session_id: str | None = Query(default=None, max_length=200, description="Filtra por sessão."),
    memory: MemoryService = Depends(get_memory_service),
) -> list[MemoryResult]:
    """Busca semântica nas memórias — expõe o `recall` (usado pelo agente) via HTTP.

    Declarada ANTES de `/memories/{memory_id}` para não ser capturada como id.
    """
    return await memory.recall(q, limit, min_score, topic, session_id=session_id)


@router.get("/topics", response_model=list[str])
async def list_topics(
    limit: int = Query(default=50, ge=1, le=200, description="Quantidade máxima de tópicos."),
    memory: MemoryService = Depends(get_memory_service),
) -> list[str]:
    """Lista os tópicos distintos das memórias existentes (limitado a `limit`)."""
    return await memory.list_topics(limit=limit)


@router.get("/topics/counts", response_model=list[TopicCount])
async def list_topic_counts(
    limit: int = Query(default=50, ge=1, le=200, description="Quantidade máxima de tópicos."),
    memory: MemoryService = Depends(get_memory_service),
) -> list[TopicCount]:
    """Lista os tópicos com a contagem de memórias de cada um (para a sidebar)."""
    return await memory.topic_counts(limit=limit)


@router.patch("/topics", response_model=TopicRenamed)
async def rename_topic(
    payload: TopicRename,
    memory: MemoryService = Depends(get_memory_service),
) -> TopicRenamed:
    """Renomeia um tópico (e todas as memórias dele) — o "renomear" da sidebar.

    O nome atual vai no corpo porque tópico é texto livre e pode conter `/`, o
    que exigiria escaping no path. Desfechos: 404 se o tópico de origem não
    existir, 409 se o nome desejado já for de outro tópico (evita fundir dois
    tópicos em silêncio) e 503 se o armazenamento estiver indisponível.
    """
    result = await memory.rename_topic(payload.topic, payload.name)
    if result.status is RenameTopicStatus.UNAVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="armazenamento indisponível: não foi possível renomear o tópico",
        )
    if result.status is RenameTopicStatus.NOT_FOUND:
        raise HTTPException(status_code=404, detail="tópico não encontrado")
    if result.status is RenameTopicStatus.CONFLICT:
        raise HTTPException(
            status_code=409,
            detail=f"já existe um tópico chamado '{payload.name}'",
        )
    return TopicRenamed(topic=payload.name, updated=result.updated)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    memory: MemoryService = Depends(get_memory_service),
) -> Response:
    """Remove uma memória pelo id; 503 se o armazenamento não confirmou a remoção."""
    if not await memory.delete(memory_id):
        raise HTTPException(
            status_code=503,
            detail="armazenamento indisponível: não foi possível remover a memória",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/memories/{memory_id}", response_model=StoredMemory)
async def get_memory(
    memory_id: str,
    memory: MemoryService = Depends(get_memory_service),
    store: VectorStore = Depends(get_vector_store),
) -> StoredMemory:
    """Retorna uma memória pelo id; 404 se não existir; 503 se o Qdrant estiver
    offline e não der para verificar (não mente "não encontrada" — um 404 falso
    numa indisponibilidade transitória faria o cliente recriar e duplicar)."""
    found = await memory.get(memory_id)
    if found is None:
        if not await store.ping():
            raise HTTPException(
                status_code=503,
                detail="armazenamento de memória indisponível: não é possível verificar a memória",
            )
        raise HTTPException(status_code=404, detail="memória não encontrada")
    return found


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    memory: MemoryService = Depends(get_memory_service),
) -> Response:
    """Remove todas as memórias de uma sessão de conversa; 503 se não confirmado."""
    if not await memory.delete_session(session_id):
        raise HTTPException(
            status_code=503,
            detail="armazenamento indisponível: não foi possível remover a sessão",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)