"""Router de chat com o agente Pydantic AI imbuído de memória.

Expõe `POST /api/chat` (resposta completa) e `POST /api/chat/stream`
(resposta em Server-Sent Events, token a token).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from openai import OpenAIError

from app.api.deps import get_agent_service
from app.models.chat import ChatRequest, ChatResponse
from app.services.agent_service import AgentService

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    agent: AgentService = Depends(get_agent_service),
) -> ChatResponse:
    """Processa uma mensagem com recuperação automática de memórias."""
    result = await agent.chat(request.message, request.session_id)
    return ChatResponse(
        response=result.response,
        memories_used=result.memories_used,
        session_id=request.session_id,
    )


def _sse(data: dict[str, object]) -> str:
    """Serializa um evento como uma linha SSE `data: {...}\\n\\n`."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    agent: AgentService = Depends(get_agent_service),
) -> StreamingResponse:
    """Responde via Server-Sent Events com tokens do agente.

    Emite `{"type": "token", "content": ...}` durante a geração e
    `{"type": "done", "memories_used": N}` ao final. Se a OpenAI falhar em
    pleno stream, emite `{"type": "error", "detail": ...}` — nunca um 500
    nem um stream truncado.
    """

    async def event_source() -> AsyncIterator[str]:
        try:
            async for event in agent.stream_chat(request.message, request.session_id):
                data: dict[str, object] = {"type": event.type}
                if event.type == "done":
                    data["memories_used"] = event.memories_used
                else:
                    data["content"] = event.content
                yield _sse(data)
        except OpenAIError as exc:
            yield _sse({"type": "error", "detail": str(exc)})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )