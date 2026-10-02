"""Testa que o EmbeddingService respeita OPENAI_BASE_URL (endpoint OpenAI-compatível).

Permitir apontar para um servidor self-hosted desacopla o projeto da OpenAI.
"""

from __future__ import annotations

from app.core.config import Settings
from app.services.embedding_service import EmbeddingService


def test_embedding_client_uses_configured_base_url() -> None:
    """Com OPENAI_BASE_URL definido, o cliente aponta para esse endpoint."""
    cfg = Settings(openai_api_key="x", openai_base_url="http://localhost:11434/v1")
    client = EmbeddingService(config=cfg)._get_client()
    assert str(client.base_url).startswith("http://localhost:11434/v1")


def test_embedding_client_defaults_to_openai_when_unset() -> None:
    """Sem OPENAI_BASE_URL, mantém o endpoint padrão da OpenAI (sem regressão)."""
    cfg = Settings(openai_api_key="x")
    client = EmbeddingService(config=cfg)._get_client()
    assert "api.openai.com" in str(client.base_url)
