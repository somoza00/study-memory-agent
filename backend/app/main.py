"""Entrypoint da aplicação.

Cria a instância FastAPI, configura a observabilidade (OTEL → Langfuse) no
lifespan e monta os routers de saúde, chat e memórias. A lógica de negócio
vive em api/routers e services; este módulo apenas monta o app.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers.chat import router as chat_router
from app.api.routers.health import router as health_router
from app.api.routers.memories import router as memories_router
from app.services.observability import configure_langfuse_otel


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Configura o tracing OTel nativo do Pydantic AI apontando para o Langfuse."""
    configure_langfuse_otel()
    yield


app = FastAPI(title="Study Memory Agent", version="0.1.0", lifespan=lifespan)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(memories_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """Banner simples para confirmar que o serviço está no ar."""
    return {"service": "study-memory-agent", "status": "ok"}