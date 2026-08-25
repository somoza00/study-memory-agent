"""Router de health check.

Expõe GET /health, usado pelo healthcheck do Docker Compose para confirmar
que o backend subiu. Não depende de Qdrant nem de OpenAI.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Retorna status de prontidão do serviço."""
    return {"status": "ok"}
