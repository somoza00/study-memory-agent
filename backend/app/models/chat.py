"""Contratos de chat: mensagens e resposta do agente."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


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
    topic: str | None = Field(
        default=None,
        max_length=120,
        description="Filtra a recuperação de memória para um tópico específico (opcional).",
    )

    @field_validator("message")
    @classmethod
    def _reject_blank_message(cls, value: str) -> str:
        """Mensagem só com espaços não gera resposta útil; rejeita (422) antes."""
        if not value.strip():
            raise ValueError("message não pode conter apenas espaços")
        return value


class ChatResponse(BaseModel):
    """Payload de saída de `POST /api/chat`."""

    response: str = Field(..., description="Resposta gerada pelo agente.")
    memories_used: int = Field(..., ge=0, description="Quantidade de memórias injetadas no prompt.")
    session_id: str = Field(..., description="Eco da sessão da requisição.")