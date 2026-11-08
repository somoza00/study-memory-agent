"""Testes do `VectorStore.ping`: sonda de readiness limitada por tempo.

`/health/ready` (usado pelo healthcheck do compose, `timeout: 5s`) e
`/api/health` chamam `ping()`. Sem teto, a sonda ficava presa no timeout default
do httpx (5s) — o mesmo orçamento do healthcheck — então um Qdrant que aceita a
conexão e não responde fazia o Docker matar a sonda por timeout em vez de
receber o 503 "degraded".
"""

from __future__ import annotations

import asyncio
import time

from app.services.vector_store import VectorStore


class _OkQdrant:
    """Cliente que responde na hora."""

    async def get_collections(self) -> None:
        return None


class _BrokenQdrant:
    """Cliente que falha na hora (conexão recusada)."""

    async def get_collections(self) -> None:
        raise RuntimeError("conexão recusada")


class _HungQdrant:
    """Cliente que aceita a chamada e nunca responde (conexão meio-aberta)."""

    async def get_collections(self) -> None:
        await asyncio.sleep(60)


def _store(client: object) -> VectorStore:
    """`VectorStore` com um cliente stub (sem Qdrant de verdade)."""
    return VectorStore(client=client, vector_size=3)  # type: ignore[arg-type]


async def test_ping_ok_quando_o_qdrant_responde() -> None:
    assert await _store(_OkQdrant()).ping() is True


async def test_ping_false_quando_o_qdrant_falha() -> None:
    assert await _store(_BrokenQdrant()).ping() is False


async def test_ping_desiste_dentro_do_orcamento_do_healthcheck() -> None:
    """Sonda pendurada vira `False` em ~2s, não nos 5s do timeout do healthcheck.

    O healthcheck do compose tem `timeout: 5s`: se a sonda levar isso, o Docker
    mata a chamada e conta falha em vez de receber o 503 — o container fica
    "unhealthy" por timeout, sem a resposta que diria qual dependência caiu.
    """
    started = time.monotonic()
    assert await _store(_HungQdrant()).ping() is False
    elapsed = time.monotonic() - started
    assert elapsed < 4.0, f"ping levou {elapsed:.1f}s — estouraria o timeout: 5s do healthcheck"
