"""Router de chat com o agente Pydantic AI imbuído de memória.

Expõe `POST /api/chat` (resposta completa) e `POST /api/chat/stream`
(resposta em Server-Sent Events, token a token).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openai import OpenAIError

from app.api.deps import get_agent_service
from app.models.chat import ChatRequest, ChatResponse
from app.services.agent_service import (
    AgentService,
    AgentTimeoutError,
    ProviderNotConfiguredError,
    StreamEvent,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])

# Comentário SSE (`: ping`) emitido a cada N segundos SEM token. Um provedor
# pode levar dezenas de segundos até o primeiro token (o agente tem teto de
# `AGENT_TIMEOUT_SECONDS`), e nesse intervalo o servidor não escreve nada: um
# proxy/CDN no meio do caminho fecha conexão ociosa pelo próprio default (nginx
# `proxy_read_timeout` 60s, Cloudflare 100s) e o cliente recebe o stream
# truncado NO MEIO — exatamente o desfecho que o contrato "nunca um stream
# truncado" promete evitar. O `: ping` é um comentário pela especificação de SSE
# (EventSource e o parser do frontend, que só olha linhas `data:`, ignoram), e
# serve só para manter a conexão viva enquanto o modelo "pensa".
_SSE_KEEPALIVE_SECONDS = 15.0


def _consume_task_result(task: asyncio.Task[None]) -> None:
    """Descarta o resultado/exceção da task do agente (cancelada ao fim do stream)."""
    with suppress(asyncio.CancelledError, Exception):
        task.exception()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    agent: AgentService = Depends(get_agent_service),
) -> ChatResponse:
    """Processa uma mensagem com recuperação de memórias (filtro `topic` opcional)."""
    try:
        result = await agent.chat(
            request.message, request.session_id, request.topic, model=request.model
        )
    except ProviderNotConfiguredError as exc:
        # Provedor não configurado é problema de deploy, não falha de provider:
        # 503 com o motivo, nunca o 500 cru que saía da construção do agente.
        logger.error("chat sem provedor configurado: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "nenhum provedor de LLM configurado: defina OPENAI_API_KEY "
                "(ou OPENAI_BASE_URL para um endpoint OpenAI-compatível)"
            ),
        ) from exc
    except AgentTimeoutError as exc:
        # 504 (Gateway Timeout): o provedor aceitou a conexão e não respondeu.
        # Sem um tipo próprio isto caía no `except Exception` abaixo e virava
        # 502 "erro interno", culpando o app por uma indisponibilidade do
        # provedor — e o cliente não sabia que podia tentar de novo.
        raise HTTPException(
            status_code=504, detail=f"O modelo não respondeu a tempo: {exc}"
        ) from exc
    except OpenAIError as exc:
        # Espelha o tratamento do endpoint de streaming: falha do provider
        # vira uma resposta de erro estruturada (502), não um 500 cru.
        raise HTTPException(
            status_code=502, detail=f"Falha ao processar com o modelo: {exc}"
        ) from exc
    except Exception as exc:
        # Espelha o /api/chat/stream: erro não-OpenAI vira 502 estruturado,
        # nunca 500 cru (regra do AGENTS.md).
        logger.exception("chat falhou com erro não-OpenAI")
        raise HTTPException(status_code=502, detail=f"Erro interno: {exc}") from exc
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

    # O agente roda numa task separada e o gerador só consome a fila. Dar
    # `asyncio.wait_for` direto no `__anext__` do agente CANCELA a leitura no
    # timeout (é o que `wait_for` faz com o que está esperando) — um keep-alive
    # assim fecharia justamente o stream que ele existe para proteger.
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

    async def pump() -> None:
        """Consome o agente e empurra para a fila; erros viram evento, como antes."""
        try:
            async for event in agent.stream_chat(
                request.message, request.session_id, request.topic, model=request.model
            ):
                queue.put_nowait(("event", event))
        except ProviderNotConfiguredError as exc:
            logger.error("stream sem provedor configurado: %s", exc)
            queue.put_nowait(
                (
                    "error",
                    "nenhum provedor de LLM configurado: defina OPENAI_API_KEY "
                    "(ou OPENAI_BASE_URL para um endpoint OpenAI-compatível)",
                )
            )
        except AgentTimeoutError as exc:
            # Streaming: os headers já foram enviados (200), então o erro vai
            # como evento — mas com a mensagem certa, não "erro interno".
            queue.put_nowait(("error", f"O modelo não respondeu a tempo: {exc}"))
        except OpenAIError as exc:
            queue.put_nowait(("error", str(exc)))
        except Exception as exc:
            # Garante o contrato documentado "nunca um stream truncado": qualquer
            # exceção não-OpenAI vira um evento de erro, em vez de abortar a
            # conexão no meio (headers já enviados).
            logger.exception("stream_chat falhou com erro não-OpenAI")
            queue.put_nowait(("error", f"Erro interno: {exc}"))
        finally:
            queue.put_nowait(("end", None))

    async def event_source() -> AsyncIterator[str]:
        task = asyncio.create_task(pump())
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(
                        queue.get(), timeout=_SSE_KEEPALIVE_SECONDS
                    )
                except TimeoutError:
                    yield ": ping\n\n"  # silêncio do provedor: mantém a conexão viva
                    continue
                if kind == "end":
                    return
                if kind == "error":
                    yield _sse({"type": "error", "detail": cast("str", payload)})
                    continue
                event = cast("StreamEvent", payload)
                data: dict[str, object] = {"type": event.type}
                if event.type == "done":
                    data["memories_used"] = event.memories_used
                else:
                    data["content"] = event.content
                yield _sse(data)
        finally:
            # Cliente desconectou (GeneratorExit) ou o stream terminou: a task do
            # agente não pode continuar chamando o provedor sozinha. O callback
            # consome a exceção da task, senão o cancelamento vira "Task
            # exception was never retrieved" no log.
            task.add_done_callback(_consume_task_result)
            task.cancel()

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )