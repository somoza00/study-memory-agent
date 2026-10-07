"""Agente Pydantic AI que injeta memórias recuperadas no prompt.

O agente expõe três tools (`store_memory`, `recall_memory`, `list_topics`)
que operam sobre o `MemoryService` recebido por injeção. Em `chat`, as
memórias relevantes à mensagem são recuperadas antes da chamada e injetadas
no system prompt (instruções); o modelo também pode chamar `recall_memory`
durante a conversa. A instrumentação usa o OTEL nativo do Pydantic AI
(`agent.instrument`), sem LangfuseCallbackHandler.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date

from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.core.config import Settings, settings
from app.models.memory import MemoryMetadata, MemoryResult
from app.services.memory_service import MemoryService

logger = logging.getLogger(__name__)


class ProviderNotConfiguredError(RuntimeError):
    """O provedor do agente não pôde ser inicializado (credencial/endpoint).

    Existe para o router responder um status estruturado (503) em vez do 500 cru
    que acontecia quando a exceção subia na resolução da dependência do FastAPI.
    """


DEFAULT_INSTRUCTIONS = (
    "Você é um assistente de estudos com memória persistente. "
    "Use as memórias do usuário injetadas abaixo como contexto ao responder. "
    "Grave novos aprendizados com store_memory, busque contexto com recall_memory "
    "e descubra tópicos já estudados com list_topics. Antes de criar um tópico novo, "
    "chame list_topics e reutilize o tópico existente que já cubra o assunto — "
    "tópicos duplicados (mesmo assunto com nomes diferentes) poluem a lista do usuário. "
    "Responda sempre em português, de forma clara e direta."
)


@dataclass
class AgentDeps:
    """Dependências entregues ao agente a cada run: memória, sessão e contexto."""

    memory: MemoryService
    session_id: str
    context: list[MemoryResult]
    # Limiar de similaridade do recall (vem de `Settings`, não fixo no código).
    threshold: float = 0.7
    # Filtro de sessão do recall: None = busca em todas as sessões (default).
    session_filter: str | None = None


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
        self._agent: Agent[AgentDeps, str] | None = None
        self._agent_error: Exception | None = None
        try:
            self._agent = self._build_agent()
        except Exception as exc:
            # Credencial ausente/endpoint inválido não pode explodir aqui: esta
            # dependência é resolvida pelo FastAPI ANTES do corpo da rota, então
            # a exceção escapava do try/except do router e virava 500 cru.
            # Guardamos o erro e devolvemos 503 estruturado quando o chat é usado.
            self._agent_error = exc
            logger.error("provedor do agente não pôde ser inicializado: %s", exc)

    def _require_agent(self) -> Agent[AgentDeps, str]:
        """Devolve o agente, ou falha com `ProviderNotConfiguredError`."""
        if self._agent is None:
            raise ProviderNotConfiguredError(str(self._agent_error)) from self._agent_error
        return self._agent

    def _build_provider(self) -> OpenAIProvider:
        """Monta o provider do agente apontando para o endpoint configurado.

        Sem `OPENAI_EXTRA_HEADERS` usa o caminho simples (api_key/base_url). Com
        headers extras (ex.: `x-opencode-session`, exigido pelo OpenCode Go)
        constrói o cliente OpenAI à mão, porque `OpenAIProvider` não expõe
        `default_headers` — só aceita um `AsyncOpenAI` já pronto.
        """
        headers = self._config.openai_extra_headers
        if not headers:
            return OpenAIProvider(
                api_key=self._config.openai_api_key,
                # None preserva o endpoint padrão da OpenAI; um valor aponta o
                # agente para qualquer endpoint OpenAI-compatível (local/self-hosted).
                base_url=self._config.openai_base_url,
            )
        client = AsyncOpenAI(
            # Endpoint compatível pode não exigir chave; o SDK exige uma string
            # não-vazia, então usamos o mesmo placeholder do Pydantic AI.
            api_key=self._config.openai_api_key or "api-key-not-set",
            base_url=self._config.openai_base_url,
            default_headers=headers,
        )
        return OpenAIProvider(openai_client=client)

    def _build_agent(self) -> Agent[AgentDeps, str]:
        """Constrói o agente, registra tools/instruções e ativa o OTEL nativo."""
        provider = self._build_provider()
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
            # Reusa a grafia de um tópico existente quando só a caixa difere:
            # o modelo escolhe a string livremente ("FastAPI" vs "fastapi") e
            # tópicos duplicados aparecem separados na sidebar.
            topic = await ctx.deps.memory.canonical_topic(topic)
            metadata = MemoryMetadata(
                topic=topic,
                source=source,
                date=date.today(),
                session_id=ctx.deps.session_id,
            )
            memory_id, persisted = await ctx.deps.memory.store(text, metadata)
            if not persisted:
                return (
                    f"Não foi possível gravar a memória ({memory_id}): "
                    "armazenamento vetorial indisponível"
                )
            return f"Memória gravada com sucesso ({memory_id})."

        @agent.tool
        async def recall_memory(
            ctx: RunContext[AgentDeps],
            query: str,
            limit: int = 5,
            min_score: float | None = None,
            topic: str | None = None,
        ) -> list[dict[str, object]]:
            """Busca memórias relacionadas a `query`, filtradas por `topic` se informado.

            `min_score` vazio usa o limiar configurado (`RECALL_MIN_SCORE` ou o
            default do provedor de embedding).
            """
            limit = max(1, min(int(limit), 20))  # teto p/ controlar tokens do recall
            threshold = ctx.deps.threshold if min_score is None else min_score
            results = await ctx.deps.memory.recall(
                query, limit, threshold, topic, session_id=ctx.deps.session_filter
            )
            return [r.model_dump(mode="json") for r in results]

        @agent.tool
        async def list_topics(ctx: RunContext[AgentDeps]) -> list[str]:
            """Lista os tópicos distintos já estudados pelo usuário."""
            return await ctx.deps.memory.list_topics()

        return agent

    def _recall_session_filter(self, session_id: str) -> str | None:
        """Filtro de sessão do recall: None quando o escopo é "todas as sessões".

        Com escopo por sessão (e o frontend criando uma sessão nova a cada
        reload) o agente não enxergava nada do que o usuário estudou antes — o
        oposto da promessa de memória persistente entre sessões.
        """
        return session_id if self._config.recall_scope == "session" else None

    async def chat(self, message: str, session_id: str, topic: str | None = None) -> ChatResult:
        """Recupera memórias (opcionalmente de um `topic`) e gera a resposta."""
        agent = self._require_agent()
        session_filter = self._recall_session_filter(session_id)
        memories = await self._memory.recall(
            message,
            self._config.recall_limit,
            self._config.recall_score_threshold,
            topic,
            session_id=session_filter,
        )
        deps = AgentDeps(
            memory=self._memory,
            session_id=session_id,
            context=memories,
            threshold=self._config.recall_score_threshold,
            session_filter=session_filter,
        )
        result = await agent.run(message, deps=deps)
        return ChatResult(response=str(result.output), memories_used=len(memories))

    async def stream_chat(
        self, message: str, session_id: str, topic: str | None = None
    ) -> AsyncIterator[StreamEvent]:
        """Gera tokens de resposta em streaming (SSE) via `agent.run_stream`.

        Recupera memórias relevantes antes de iniciar o stream (mesmo
        comportamento de `chat`) e emite `StreamEvent` de tipo `token` a cada
        delta de texto, terminando com `done` + `memories_used`.
        """
        agent = self._require_agent()
        session_filter = self._recall_session_filter(session_id)
        memories = await self._memory.recall(
            message,
            self._config.recall_limit,
            self._config.recall_score_threshold,
            topic,
            session_id=session_filter,
        )
        deps = AgentDeps(
            memory=self._memory,
            session_id=session_id,
            context=memories,
            threshold=self._config.recall_score_threshold,
            session_filter=session_filter,
        )
        async with agent.run_stream(message, deps=deps) as agent_run:
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