"""Router de memórias: listagem, tópicos e remoção.

Expõe:
- `GET    /api/memories?topic=&limit=`   → lista memórias (filtro opcional por tópico)
- `GET    /api/topics`                    → tópicos distintos existentes
- `DELETE /api/memories/{id}`            → remove uma memória pelo id
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from openai import OpenAIError

from app.api.deps import get_memory_service
from app.models.memory import MemoryCreate, MemoryCreated, MemoryMetadata, StoredMemory
from app.services.memory_service import MemoryService

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
    return MemoryCreated(id=memory_id, persisted=persisted, metadata=metadata)


@router.get("/memories", response_model=list[StoredMemory])
async def list_memories(
    topic: str | None = Query(default=None, description="Filtra memórias por tópico."),
    session_id: str | None = Query(
        default=None, max_length=200, description="Filtra memórias por sessão de conversa."
    ),
    limit: int = Query(default=20, ge=1, le=100, description="Quantidade máxima de itens."),
    memory: MemoryService = Depends(get_memory_service),
) -> list[StoredMemory]:
    """Lista memórias persistidas, opcionalmente filtradas por `topic` e/ou `session_id`."""
    return await memory.list(topic=topic, limit=limit, session_id=session_id)


@router.get("/topics", response_model=list[str])
async def list_topics(
    memory: MemoryService = Depends(get_memory_service),
) -> list[str]:
    """Lista os tópicos distintos das memórias existentes."""
    return await memory.list_topics()


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    memory: MemoryService = Depends(get_memory_service),
) -> Response:
    """Remove uma memória pelo id."""
    await memory.delete(memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/memories/{memory_id}", response_model=StoredMemory)
async def get_memory(
    memory_id: str,
    memory: MemoryService = Depends(get_memory_service),
) -> StoredMemory:
    """Retorna uma memória pelo id; 404 se não existir."""
    found = await memory.get(memory_id)
    if found is None:
        raise HTTPException(status_code=404, detail="memória não encontrada")
    return found


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    memory: MemoryService = Depends(get_memory_service),
) -> Response:
    """Remove todas as memórias de uma sessão de conversa."""
    await memory.delete_session(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)