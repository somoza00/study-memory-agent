"""Router de health check.

Expõe `GET /health` (usado pelo healthcheck do Docker Compose) e
`GET /api/health` (health detalhado que reporta conectividade com o Qdrant,
degradando sem 500 quando o Qdrant está offline).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.api.deps import get_vector_store
from app.services.vector_store import VectorStore

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Retorna status de prontidão do serviço."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(
    response: Response, store: VectorStore = Depends(get_vector_store)
) -> dict[str, object]:
    """Readiness de verdade: 503 quando o Qdrant não responde.

    Separado do `/health` de propósito: liveness não pode falhar por causa de uma
    dependência (senão um Qdrant momentaneamente fora derruba o container que
    está sadio). Quem usa este endpoint é o healthcheck do Docker Compose — antes
    ele apontava para `/health`, que devolve `{"status": "ok"}` fixo e nunca olha
    o Qdrant, então o container ficava "healthy" com o banco vetorial caído e o
    `depends_on: service_healthy` não significava nada.
    """
    qdrant_up = await store.ping()
    if not qdrant_up:
        response.status_code = 503
    return {
        "status": "ready" if qdrant_up else "degraded",
        "dependencies": {"qdrant": "up" if qdrant_up else "down"},
    }


@router.get("/api/health")
async def deep_health(store: VectorStore = Depends(get_vector_store)) -> dict[str, object]:
    """Health detalhado: reporta conectividade com o Qdrant (degrade, nunca 500)."""
    qdrant_up = await store.ping()
    return {
        "status": "ok" if qdrant_up else "degraded",
        "dependencies": {"qdrant": "up" if qdrant_up else "down"},
    }