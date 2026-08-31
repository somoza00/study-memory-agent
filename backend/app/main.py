"""Entrypoint da aplicação.

Cria a instância FastAPI, configura a observabilidade (OTEL → Langfuse) no
lifespan e monta os routers de saúde, chat e memórias. A lógica de negócio
vive em api/routers e services; este módulo apenas monta o app.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.api.routers.chat import router as chat_router
from app.api.routers.health import router as health_router
from app.api.routers.memories import router as memories_router
from app.core.logging import configure_logging
from app.core.security import require_api_key
from app.services.observability import configure_langfuse_otel


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Configura logging (com redação de segredos) e o tracing OTel → Langfuse."""
    configure_logging()
    configure_langfuse_otel()
    yield


app = FastAPI(title="Study Memory Agent", version="0.1.0", lifespan=lifespan)

# Auth (X-API-Key) aplicada às rotas /api de chat e memórias; /health e
# /api/health ficam abertos para o healthcheck de orquestração.
app.include_router(chat_router, dependencies=[Depends(require_api_key)])
app.include_router(memories_router, dependencies=[Depends(require_api_key)])
app.include_router(health_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """Banner simples para confirmar que o serviço está no ar."""
    return {"service": "study-memory-agent", "status": "ok"}