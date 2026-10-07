"""Gera embeddings de texto para as memórias.

Dois provedores, escolhidos por `EMBEDDING_PROVIDER`:

- `openai` (default): endpoint OpenAI-compatível (`EMBEDDING_BASE_URL` /
  `EMBEDDING_API_KEY`, herdando as do agente quando vazias).
- `local`: ONNX no próprio processo, via `fastembed` — sem chave e sem chamada
  de rede depois do primeiro download dos pesos. Necessário porque provedores de
  chat como o OpenCode Zen/Go expõem só `/chat/completions`, não `/embeddings`.

O modelo remoto e a API key vêm de `Settings`, mas ambos podem ser sobrescritos
na injeção para permitir mocks em teste.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from openai import AsyncOpenAI

from app.core.config import Settings, settings

if TYPE_CHECKING:
    from fastembed import TextEmbedding


@runtime_checkable
class LocalEmbedder(Protocol):
    """Contrato mínimo do embedder local (implementado pelo `TextEmbedding`)."""

    def embed(self, documents: Iterable[str]) -> Iterable[Sequence[float]]: ...


class EmbeddingService:
    """Gera embeddings de texto usando o provedor configurado."""

    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        config: Settings = settings,
        local_model: LocalEmbedder | None = None,
    ) -> None:
        self._client = client
        self._local = local_model
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
            self._client = AsyncOpenAI(
                api_key=self._config.embedding_key,
                # Endpoint próprio dos embeddings (`EMBEDDING_BASE_URL`, com
                # fallback para o do agente); None preserva o padrão da OpenAI.
                base_url=self._config.embedding_endpoint,
            )
        return self._client

    def _get_local_model(self) -> TextEmbedding:
        """Carrega o modelo ONNX, baixando os pesos na primeira chamada.

        O import é tardio de propósito: quem usa o provedor remoto não precisa
        da dependência opcional `local-embeddings` instalada.
        """
        if self._local is None:
            from fastembed import TextEmbedding

            self._local = TextEmbedding(
                model_name=self._config.local_embedding_model,
                cache_dir=self._config.embedding_cache_dir,
            )
        return self._local

    async def embed(self, text: str) -> list[float]:
        """Retorna o vetor de embedding para `text`."""
        if self._config.embedding_provider == "local":
            vector = await asyncio.to_thread(self._embed_local, text)
        else:
            vector = await self._embed_remote(text)
        return self._check_dim(vector)

    async def _embed_remote(self, text: str) -> list[float]:
        """Embedding via endpoint OpenAI-compatível."""
        response = await self._get_client().embeddings.create(input=text, model=self._model)
        return [float(value) for value in response.data[0].embedding]

    def _embed_local(self, text: str) -> list[float]:
        """Embedding local (roda em thread: ONNX é CPU-bound e bloquearia o loop)."""
        vectors = list(self._get_local_model().embed([text]))
        return [float(value) for value in vectors[0]]

    def _check_dim(self, vector: list[float]) -> list[float]:
        """Falha explícita se o modelo não casar com `EMBEDDING_DIM`.

        Sem isto, um `EMBEDDING_DIM` desalinhado só apareceria como erro obscuro
        do Qdrant (ou como memória "não persistida" sem causa visível).
        """
        expected = self._config.embedding_dim
        if len(vector) != expected:
            raise ValueError(
                f"Embedding de {len(vector)} dimensões, mas EMBEDDING_DIM={expected}. "
                "Ajuste EMBEDDING_DIM ao modelo e recrie a collection do Qdrant."
            )
        return vector
