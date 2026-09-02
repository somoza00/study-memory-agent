"""Contratos de chat: mensagens e resposta do agente."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Payload de entrada de `POST /api/chat`."""

    message: str = Field(
        ..., min_length=1, max_length=10_000, description="Mensagem do usuário."
    )
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Identificador da sessão de conversa.",
    )


class ChatResponse(BaseModel):
    """Payload de saída de `POST /api/chat`."""

    response: str = Field(..., description="Resposta gerada pelo agente.")
    memories_used: int = Field(..., ge=0, description="Quantidade de memórias injetadas no prompt.")
    session_id: str = Field(..., description="Eco da sessão da requisição.")