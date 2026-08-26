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
        self._client = client
        self._config = config
        self._model = config.embedding_model

    def _get_client(self) -> AsyncOpenAI:
        """Retorna o cliente OpenAI, criando-o sob demanda (lazy).

        Permitir chave vazia na construção (ex.: sem `.env`) mantém os
        endpoints que não geram embedding (listagem/topics/delete) funcionando
        com graceful degradation; apenas a geração de embedding de fato exige
        credencial válida.
        """
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self._config.openai_api_key)
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Retorna o vetor de embedding para `text`."""
        response = await self._get_client().embeddings.create(input=text, model=self._model)
        return response.data[0].embedding
