"""Modelo de domínio Memory.

Representa uma unidade de estudo persistida: texto + metadata
(topic, source, date, session_id).
"""

from __future__ import annotations

from datetime import date as date_

from pydantic import BaseModel, Field


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
