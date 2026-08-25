"""Gera embeddings via OpenAI `text-embedding-3-small`.

Encapsula o cliente OpenAI async. O modelo e a API key vêm de `Settings`,
mas ambos podem ser sobrescritos na injeção para permitir mocks em teste.
"""

from __future__ import annotations

from openai import AsyncOpenAI

from app.core.config import Settings, settings


class EmbeddingService:
    """Gera embeddings de texto usando a API de embeddings da OpenAI."""

    def __init__(self, client: AsyncOpenAI | None = None, config: Settings = settings) -> None:
        self._client = client or AsyncOpenAI(api_key=config.openai_api_key)
        self._model = config.embedding_model

    async def embed(self, text: str) -> list[float]:
        """Retorna o vetor de embedding para `text`."""
        response = await self._client.embeddings.create(input=text, model=self._model)
        return response.data[0].embedding
