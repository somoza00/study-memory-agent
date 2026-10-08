"""Integração com Langfuse via OTEL nativo do Pydantic AI.

Configura um `TracerProvider` global de OpenTelemetry com um exporter
OTLP/HTTP apontando para o endpoint OTel do Langfuse. O agente
(`AgentService`) ativa `agent.instrument = True`, fazendo o Pydantic AI
emitir spans nativos (OpenTelemetry GenAI) para o Langfuse — sem usar o
`LangfuseCallbackHandler`.
"""

from __future__ import annotations

import base64

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.config import Settings, settings

_service = "study-memory-agent"


def _basic_auth(public_key: str, secret_key: str) -> str:
    """Monta o header Authorization Basic exigido pelo endpoint OTel do Langfuse."""
    token = f"{public_key}:{secret_key}".encode()
    return "Basic " + base64.b64encode(token).decode()


def configure_langfuse_otel(config: Settings = settings) -> None:
    """Configura o `TracerProvider` global do OpenTelemetry para exportar ao Langfuse.

    Só monta o exporter com `LANGFUSE_ENABLED=true`: sem o Langfuse no ar o
    exporter falha a cada span (e o SDK fica tentando), o que enchia o log de
    "Failed to export span batch" no uso normal do app — o README promete que
    sem Langfuse o app roda igual, e agora isso vale também para o log.
    """
    if not config.langfuse_enabled:
        return
    endpoint = f"{config.langfuse_host.rstrip('/')}/api/public/otel/v1/traces"
    exporter = OTLPSpanExporter(
        endpoint=endpoint,
        headers={
            "Authorization": _basic_auth(config.langfuse_public_key, config.langfuse_secret_key),
        },
    )
    resource = Resource.create(
        {
            "service.name": _service,
            "deployment.environment": config.environment,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)