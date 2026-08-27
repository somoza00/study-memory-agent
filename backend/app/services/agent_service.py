"""Agente Pydantic AI que injeta memórias recuperadas no prompt.

O agente expõe três tools (`store_memory`, `recall_memory`, `list_topics`)
que operam sobre o `MemoryService` recebido por injeção. Em `chat`, as
memórias relevantes à mensagem são recuperadas antes da chamada e injetadas
no system prompt (instruções); o modelo também pode chamar `recall_memory`
durante a conversa. A instrumentação usa o OTEL nativo do Pydantic AI
(`agent.instrument`), sem LangfuseCallbackHandler.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.core.config import Settings, settings
from app.models.memory import MemoryMetadata, MemoryResult
from app.services.memory_service import MemoryService

RECALL_LIMIT = 5
RECALL_MIN_SCORE = 0.7

DEFAULT_INSTRUCTIONS = (
    "Você é um assistente de estudos com memória persistente. "
    "Use as memórias do usuário injetadas abaixo como contexto ao responder. "
    "Grave novos aprendizados com store_memory, busque contexto com recall_memory "
    "e descubra tópicos já estudados com list_topics. Responda sempre em português, "
    "de forma clara e direta."
)


@dataclass
class AgentDeps:
    """Dependências entregues ao agente a cada run: memória, sessão e contexto."""

    memory: MemoryService
    session_id: str
    context: list[MemoryResult]


@dataclass
class ChatResult:
    """Resultado do chat: texto gerado e quantas memórias foram usadas."""

    response: str
    memories_used: int


@dataclass
class StreamEvent:
    """Evento emitido durante o streaming do agente.

    `type` é `"token"` (com `content`) ou `"done"` (com `memories_used`).
    """

    type: str
    content: str = ""
    memories_used: int = 0


class AgentService:
    """Orquestra o agente Pydantic AI sobre o `MemoryService`."""

    def __init__(self, memory_service: MemoryService, config: Settings = settings) -> None:
        self._memory = memory_service
        self._config = config
        self._agent = self._build_agent()

    def _build_agent(self) -> Agent[AgentDeps, str]:
        """Constrói o agente, registra tools/instruções e ativa o OTEL nativo."""
        provider = OpenAIProvider(api_key=self._config.openai_api_key)
        model = OpenAIChatModel(model_name=self._config.agent_model, provider=provider)
        agent = Agent[AgentDeps, str](
            model,
            name="study-memory-agent",
            deps_type=AgentDeps,
            output_type=str,
            instructions=DEFAULT_INSTRUCTIONS,
        )
        agent.instrument = True  # spans OTEL nativos do Pydantic AI → Langfuse

        @agent.instructions
        def inject_memories(ctx: RunContext[AgentDeps]) -> str:
            """Injeta as memórias recuperadas no system prompt."""
            return _format_context(ctx.deps.context)

        @agent.tool
        async def store_memory(
            ctx: RunContext[AgentDeps], text: str, topic: str, source: str
        ) -> str:
            """Registra uma nova memória de estudo no Qdrant."""
            metadata = MemoryMetadata(
                topic=topic,
                source=source,
                date=date.today(),
                session_id=ctx.deps.session_id,
            )
            return await ctx.deps.memory.store(text, metadata)

        @agent.tool
        async def recall_memory(
            ctx: RunContext[AgentDeps],
            query: str,
            limit: int = 5,
            min_score: float = 0.7,
        ) -> list[dict[str, object]]:
            """Busca memórias semanticamente relacionadas a `query`."""
            results = await ctx.deps.memory.recall(query, limit, min_score)
            return [r.model_dump(mode="json") for r in results]

        @agent.tool
        async def list_topics(ctx: RunContext[AgentDeps]) -> list[str]:
            """Lista os tópicos distintos já estudados pelo usuário."""
            return await ctx.deps.memory.list_topics()

        return agent

    async def chat(self, message: str, session_id: str) -> ChatResult:
        """Recupera memórias relevantes e gera a resposta do agente."""
        memories = await self._memory.recall(message, RECALL_LIMIT, RECALL_MIN_SCORE)
        deps = AgentDeps(memory=self._memory, session_id=session_id, context=memories)
        result = await self._agent.run(message, deps=deps)
        return ChatResult(response=str(result.output), memories_used=len(memories))

    async def stream_chat(self, message: str, session_id: str) -> AsyncIterator[StreamEvent]:
        """Gera tokens de resposta em streaming (SSE) via `agent.run_stream`.

        Recupera memórias relevantes antes de iniciar o stream (mesmo
        comportamento de `chat`) e emite `StreamEvent` de tipo `token` a cada
        delta de texto, terminando com `done` + `memories_used`.
        """
        memories = await self._memory.recall(message, RECALL_LIMIT, RECALL_MIN_SCORE)
        deps = AgentDeps(memory=self._memory, session_id=session_id, context=memories)
        async with self._agent.run_stream(message, deps=deps) as agent_run:
            async for delta in agent_run.stream_text(delta=True):
                yield StreamEvent(type="token", content=delta)
        yield StreamEvent(type="done", memories_used=len(memories))


def _format_context(memories: list[MemoryResult]) -> str:
    """Serializa as memórias recuperadas para o system prompt."""
    if not memories:
        return "Nenhuma memória relevante recuperada para esta mensagem."
    lines = [
        f"- [{m.metadata.topic}] {m.text} (source: {m.metadata.source}, date: {m.metadata.date})"
        for m in memories
    ]
    return "## Memórias do usuário (contexto recuperado)\n" + "\n".join(lines)