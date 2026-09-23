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
