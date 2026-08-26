"""Settings via pydantic-settings (Qdrant, OpenAI, Langfuse).

Todos os campos têm defaults de dev para manter o app importável sem
variáveis de ambiente obrigatórias (ex.: testes, CI).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração do backend, lida de variáveis de ambiente / `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    openai_api_key: str = ""
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "study_memories"
    embedding_model: str = "text-embedding-3-small"
    agent_model: str = "gpt-4o-mini"
    environment: str = "development"
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = "pk-local"
    langfuse_secret_key: str = "sk-local"


settings = Settings()
