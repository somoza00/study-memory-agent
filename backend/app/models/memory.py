"""Modelo de domínio Memory.

Representa uma unidade de estudo persistida: texto + metadata
(topic, source, date, session_id).
"""

from __future__ import annotations

from datetime import date as date_

from pydantic import BaseModel, Field, field_validator


class MemoryMetadata(BaseModel):
    """Metadata obrigatória associada a cada memória persistida."""

    topic: str = Field(..., max_length=120)
    source: str = Field(..., max_length=200)
    date: date_
    session_id: str = Field(..., max_length=200)

    @field_validator("topic", "source", "session_id")
    @classmethod
    def _reject_blank_metadata(cls, value: str) -> str:
        """Metadata (topic/source/session_id) só com espaços polui filtros; rejeita."""
        if not value.strip():
            raise ValueError("não pode conter apenas espaços")
        return value


class MemoryResult(BaseModel):
    """Uma memória recuperada via recall, com o score de similaridade."""

    id: str
    text: str
    score: float
    metadata: MemoryMetadata


class StoredMemory(BaseModel):
    """Uma memória persistida, listada sem score (não é resultado de recall)."""

    id: str
    text: str
    metadata: MemoryMetadata


class MemoryCreate(BaseModel):
    """Payload do `POST /api/memories` (criação manual de uma memória)."""

    text: str = Field(..., min_length=1, max_length=4000, description="Texto da memória.")
    topic: str = Field(..., max_length=120)
    source: str = Field(..., max_length=200)
    session_id: str = Field(..., max_length=200)

    @field_validator("topic", "source", "session_id")
    @classmethod
    def _reject_blank_metadata(cls, value: str) -> str:
        """Metadata (topic/source/session_id) só com espaços polui filtros; rejeita (422)."""
        if not value.strip():
            raise ValueError("não pode conter apenas espaços")
        return value

    @field_validator("text")
    @classmethod
    def _reject_blank_text(cls, value: str) -> str:
        """Texto só com espaços viraria embedding-lixo; rejeita (422) antes."""
        if not value.strip():
            raise ValueError("text não pode conter apenas espaços")
        return value


class MemoryCreated(BaseModel):
    """Resposta do `POST /api/memories`."""

    id: str
    persisted: bool = Field(..., description="Se o armazenamento vetorial persistiu de fato.")
    metadata: MemoryMetadata


class TopicCount(BaseModel):
    """Um tópico e quantas memórias persistidas ele tem (para a sidebar)."""

    topic: str
    count: int


class TopicRename(BaseModel):
    """Payload do `PATCH /api/topics` (renomeia um tópico existente).

    O nome atual vai no corpo, não no path: tópico é texto livre e pode conter
    `/` (ex.: `python/asyncio`), o que exigiria escaping no path.
    """

    topic: str = Field(..., max_length=120, description="Tópico atual.")
    name: str = Field(..., min_length=1, max_length=120, description="Novo nome do tópico.")

    @field_validator("topic", "name")
    @classmethod
    def _reject_blank_topic_names(cls, value: str) -> str:
        """Nome só com espaços polui filtros e a sidebar; rejeita (422)."""
        if not value.strip():
            raise ValueError("não pode conter apenas espaços")
        return value.strip()


class TopicRenamed(BaseModel):
    """Resposta do `PATCH /api/topics`."""

    topic: str = Field(..., description="Nome novo, já aplicado.")
    updated: int = Field(..., description="Quantas memórias foram renomeadas.")