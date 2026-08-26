"""Router de chat com o agente Pydantic AI imbuído de memória.

Expõe `POST /api/chat`: recebe `{message, session_id}`, delega ao
`AgentService` e responde com o texto gerado e o número de memórias usadas.
Se o agente estiver indisponível (ex.: sem OPENAI_API_KEY), responde 503 em
vez de deixar a exceção da OpenAI virar um 500 não tratado.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_agent_service
from app.models.chat import ChatRequest, ChatResponse
from app.services.agent_service import AgentService, AgentUnavailableError

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    agent: AgentService = Depends(get_agent_service),
) -> ChatResponse:
    """Processa uma mensagem com recuperação automática de memórias."""
    try:
        result = await agent.chat(request.message, request.session_id)
    except AgentUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return ChatResponse(
        response=result.response,
        memories_used=result.memories_used,
        session_id=request.session_id,
    )