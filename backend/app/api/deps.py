"""Dependências FastAPI: instâncias únicas de serviços para os routers.

Usam `lru_cache` para singleton por processo. Em testes, os routers sobrescrevem
estas dependências via `app.dependency_overrides` (mock do agente).
"""

from __future__ import annotations

from functools import lru_cache

from app.services.agent_service import AgentService
from app.services.embedding_service import EmbeddingService
from app.services.memory_service import MemoryService
from app.services.vector_store import VectorStore


@lru_cache
def get_embedding_service() -> EmbeddingService:
    """Retorna o singleton de `EmbeddingService`."""
    return EmbeddingService()


@lru_cache
def get_vector_store() -> VectorStore:
    """Retorna o singleton de `VectorStore`."""
    return VectorStore()


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