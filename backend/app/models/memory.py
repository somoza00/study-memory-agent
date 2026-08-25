"""Modelo de domínio Memory.

Representa uma unidade de estudo persistida: texto + metadata
(topic, source, date, session_id).
"""

from __future__ import annotations

from datetime import date as date_

from pydantic import BaseModel


class MemoryMetadata(BaseModel):
    """Metadata obrigatória associada a cada memória persistida."""

    topic: str
    source: str
    date: date_
    session_id: str


class MemoryResult(BaseModel):
    """Uma memória recuperada via recall, com o score de similaridade."""

    id: str
    text: str
    score: float
    metadata: MemoryMetadata
