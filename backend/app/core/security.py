"""Autenticação por API key simples para a API pública.

A API hoje é aberta: quem alcançar o backend pode ler/escrever memórias e
gastar tokens reais de OpenAI. Esta dependência fecha as rotas /api atrás de
um header `X-API-Key` comparado em tempo constante. Enquanto `api_key` não
estiver configurado (None, dev), a checagem é pulada — o fail-closed real fica
no `config.py` (`environment=production` exige `api_key`).
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Header, HTTPException

from app.core.config import settings

security_logger = logging.getLogger("app.security")


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Valida o header `X-API-Key` contra `settings.api_key`.

    Se `api_key` não estiver configurada (default, dev), a checagem é pulada.
    Em produção isso não é possível: o Settings recusa subir sem `api_key`
    (fail-closed, ver config.py).
    """
    if settings.api_key is None:
        return
    if x_api_key is None or not hmac.compare_digest(x_api_key, settings.api_key):
        security_logger.warning("auth failed", extra={"path": "api"})
        raise HTTPException(status_code=401, detail="X-API-Key inválida ou ausente")