"""Settings via pydantic-settings (Qdrant, OpenAI, Langfuse).

Todos os campos têm defaults de dev para manter o app importável sem
variáveis de ambiente obrigatórias (ex.: testes, CI).
"""

from __future__ import annotations

from pydantic import field_validator, model_validator
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
    # Chave de autenticação da própria API (header X-API-Key) para as rotas /api.
    # None = auth desabilitada (dev). Em produção, defina para fechar a API.
    api_key: str | None = None
    environment: str = "development"
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = "pk-local"
    langfuse_secret_key: str = "sk-local"

    @field_validator("api_key", mode="before")
    @classmethod
    def _blank_api_key_means_disabled(cls, value: str | None) -> str | None:
        """`API_KEY=` vazio no .env deve significar "auth desabilitada", não
        uma chave literal de string vazia (que bloquearia toda a API)."""
        return value or None

    @model_validator(mode="after")
    def _api_key_required_in_production(self) -> Settings:
        """Fail-closed: em produção, subir sem API_KEY é um deploy aberto por
        acidente — melhor o processo nem iniciar do que servir sem auth."""
        if self.environment == "production" and self.api_key is None:
            raise ValueError(
                "environment=production exige API_KEY definida "
                "(auth da API não pode ficar desabilitada em produção)"
            )
        return self


settings = Settings()
