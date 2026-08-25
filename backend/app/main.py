"""Entrypoint da aplicação.

Cria a instância FastAPI e expõe /health para o Docker Compose reportar
prontidão. A lógica de negócio vive em api/routers e services; este módulo
apenas monta o app.
"""

from fastapi import FastAPI

from app.api.routers.health import router as health_router

app = FastAPI(title="Study Memory Agent", version="0.1.0")

app.include_router(health_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """Banner simples para confirmar que o serviço está no ar."""
    return {"service": "study-memory-agent", "status": "ok"}
