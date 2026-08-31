"""Configuração de logging (stdlib) com redação de segredos.

Implementa o que o stub prometia: um handler no logger raiz (se ainda não
existir) e um filtro de redação que troca valores de credencial conhecidos
(OpenAI, auth da própria API, Langfuse) por `***` em qualquer linha de log.
Isso evita vazar segredo via log sem depender de cada call site lembrar de
sanitizar a própria mensagem.
"""

from __future__ import annotations

import logging

from app.core.config import settings


class SecretRedactionFilter(logging.Filter):
    """Redige valores conhecidos de secret presentes na mensagem do registro."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if any(s in msg for s in self._secrets):
            for secret in self._secrets:
                msg = msg.replace(secret, "***")
            record.msg = msg
            record.args = ()
        return True


def _known_secrets() -> list[str]:
    """Valores de credencial configurados no Settings, prontos para redigir."""
    candidates = [
        settings.openai_api_key,
        settings.api_key,
        settings.langfuse_secret_key,
        settings.langfuse_public_key,
    ]
    # Deduplica preservando a ordem; descarta vazios.
    return list(dict.fromkeys(c for c in candidates if c))


def configure_logging(level: int = logging.INFO) -> None:
    """Garante um handler no logger raiz e aplica a redação de segredos.

    Idempotente: não duplica handler nem reaplica o filtro se já presente.
    Deve ser chamado uma vez no lifespan da aplicação.
    """
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    for handler in root.handlers:
        if any(isinstance(f, SecretRedactionFilter) for f in handler.filters):
            continue
        handler.addFilter(SecretRedactionFilter(_known_secrets()))