"""Testes de auth (X-API-Key) para as rotas /api.

Testam a dependência `require_api_key` de forma isolada (app mínimo, sem
tocar Qdrant/LLM) e confirmam o wiring no app real: auth nas rotas /api e
health aberto.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.core.security as security_module
from app.core.security import require_api_key
from app.main import app as real_app

_test_app = FastAPI()


@_test_app.get("/secured", dependencies=[Depends(require_api_key)])
async def _secured() -> dict[str, bool]:
    """Rota protegida usada para exercitar a dependência."""
    return {"ok": True}


@_test_app.get("/open")
async def _open() -> dict[str, bool]:
    """Rota sem auth (equivale a /health)."""
    return {"ok": True}


def test_api_key_disabled_by_default() -> None:
    """Sem api_key configurada (default, dev), a API continua aberta."""
    assert security_module.settings.api_key is None
    client = TestClient(_test_app)
    assert client.get("/secured").status_code == 200


def test_api_key_required_and_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Com api_key configurada, requests sem/com a chave errada levam 401."""
    monkeypatch.setattr(security_module.settings, "api_key", "secret123")

    client = TestClient(_test_app)
    missing = client.get("/secured")
    assert missing.status_code == 401

    wrong = client.get("/secured", headers={"X-API-Key": "wrong"})
    assert wrong.status_code == 401

    correct = client.get("/secured", headers={"X-API-Key": "secret123"})
    assert correct.status_code == 200


def test_real_app_locks_api_but_keeps_health_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No app real, /api exige chave; /health (orquestração) fica aberto."""
    monkeypatch.setattr(security_module.settings, "api_key", "secret123")

    client = TestClient(real_app)
    assert client.get("/api/memories").status_code == 401
    assert client.get("/health").status_code == 200


async def test_non_ascii_key_is_rejected_with_401_not_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Header com caractere não-ASCII vira 401, não TypeError (500).

    `hmac.compare_digest` recusa `str` não-ASCII com TypeError; o header chega
    do servidor decodificado em latin-1, então um `X-API-Key: café` cru (bytes
    UTF-8) produzia code points > 127 e a exceção subia como 500.
    """
    monkeypatch.setattr(security_module.settings, "api_key", "secret123")

    with pytest.raises(HTTPException) as excinfo:
        await require_api_key(x_api_key="café")

    assert excinfo.value.status_code == 401


async def test_ascii_key_still_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    """A comparação em bytes não muda o caminho feliz (chave correta passa)."""
    monkeypatch.setattr(security_module.settings, "api_key", "secret123")

    assert await require_api_key(x_api_key="secret123") is None