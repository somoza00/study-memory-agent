"""Router de memórias: listagem, tópicos e remoção.

Expõe:
- `GET    /api/memories?topic=&limit=`   → lista memórias (filtro opcional por tópico)
- `GET    /api/topics`                    → tópicos distintos existentes
- `DELETE /api/memories/{id}`            → remove uma memória pelo id
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import get_memory_service
from app.models.memory import StoredMemory
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/api", tags=["memories"])


@router.get("/memories", response_model=list[StoredMemory])
async def list_memories(
    topic: str | None = Query(default=None, description="Filtra memórias por tópico."),
    limit: int = Query(default=20, ge=1, le=100, description="Quantidade máxima de itens."),
    memory: MemoryService = Depends(get_memory_service),
) -> list[StoredMemory]:
    """Lista memórias persistidas, opcionalmente filtradas por `topic`."""
    return await memory.list(topic=topic, limit=limit)


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