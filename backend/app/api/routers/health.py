"""Router de health check.

Expõe `GET /health` (usado pelo healthcheck do Docker Compose) e
`GET /api/health` (health detalhado que reporta conectividade com o Qdrant,
degradando sem 500 quando o Qdrant está offline).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_vector_store
from app.services.vector_store import VectorStore

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Retorna status de prontidão do serviço."""
    return {"status": "ok"}


@router.get("/api/health")
async def deep_health(store: VectorStore = Depends(get_vector_store)) -> dict[str, object]:
    """Health detalhado: reporta conectividade com o Qdrant (degrade, nunca 500)."""
    qdrant_up = await store.ping()
    return {
        "status": "ok" if qdrant_up else "degraded",
        "dependencies": {"qdrant": "up" if qdrant_up else "down"},
    }