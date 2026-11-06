"""Dependências FastAPI: instâncias únicas de serviços para os routers.

Usam `lru_cache` para singleton por processo. Em testes, os routers sobrescrevem
estas dependências via `app.dependency_overrides` (mock do agente).

Os singletons que seguram clientes de rede (Qdrant, OpenAI dos embeddings) são
registrados em `_closables`; `close_services()` os fecha no shutdown do lifespan.
Sem isso o pool httpx de cada um ficava aberto até o processo morrer — e em
qualquer ciclo de vida por app (testes com lifespan, reload do uvicorn) sobrava
um pool órfão por instância.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from app.services.agent_service import AgentService
from app.services.embedding_service import EmbeddingService
from app.services.memory_service import MemoryService
from app.services.vector_store import VectorStore


class _Closable(Protocol):
    """Serviço com cliente de rede próprio, fechável no shutdown."""

    async def close(self) -> None: ...


# Instâncias já criadas que precisam de fechamento explícito. Lista (e não set):
# o fechamento percorre na ordem inversa de criação, como uma pilha.
_closables: list[_Closable] = []


def _track(service: _Closable) -> None:
    """Registra o serviço para ser fechado em `close_services()`."""
    _closables.append(service)


@lru_cache
def get_embedding_service() -> EmbeddingService:
    """Retorna o singleton de `EmbeddingService`."""
    service = EmbeddingService()
    _track(service)
    return service


@lru_cache
def get_vector_store() -> VectorStore:
    """Retorna o singleton de `VectorStore`."""
    store = VectorStore()
    _track(store)
    return store


@lru_cache
def get_memory_service() -> MemoryService:
    """Retorna o singleton de `MemoryService`."""
    return MemoryService(
        embedding_service=get_embedding_service(),
        vector_store=get_vector_store(),
    )


@lru_cache
def get_agent_service() -> AgentService:
    """Retorna o singleton de `AgentService` (memória injetada)."""
    return AgentService(memory_service=get_memory_service())


async def close_services() -> None:
    """Fecha os clientes de rede dos singletons e descarta os caches do `lru_cache`.

    Chamado no shutdown do lifespan. Não cria nada: fecha só o que já existe
    (um serviço lazy nunca usado — ex.: provedor de embeddings `local` — não tem
    cliente aberto e não é instanciado à toa aqui).
    """
    while _closables:
        await _closables.pop().close()
    get_agent_service.cache_clear()
    get_memory_service.cache_clear()
    get_embedding_service.cache_clear()
    get_vector_store.cache_clear()
