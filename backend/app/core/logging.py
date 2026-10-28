"""Configuração de logging (stdlib) com redação de segredos.

Implementa o que o stub prometia: um handler no logger raiz (se ainda não
existir) e um filtro de redação que troca valores de credencial conhecidos
(OpenAI, auth da própria API, Langfuse) por `***` em qualquer linha de log.
Isso evita vazar segredo via log sem depender de cada call site lembrar de
sanitizar a própria mensagem.
"""

from __future__ import annotations

import logging
import traceback

from app.core.config import settings


class SecretRedactionFilter(logging.Filter):
    """Redige valores conhecidos de secret no registro (mensagem e traceback)."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def _redact(self, text: str) -> str:
        """Troca cada secret conhecido por `***` em `text`."""
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if any(s in msg for s in self._secrets):
            record.msg = self._redact(msg)
            record.args = ()
        # O traceback também carrega o segredo: a mensagem de erro do SDK da
        # OpenAI ecoa a chave ("Incorrect API key provided: sk-..."), e o handler
        # formata o traceback DEPOIS deste filtro — então `logger.exception(...)`
        # vazava a chave mesmo com a mensagem redigida. Formatamos o traceback
        # aqui, redigimos e desligamos `exc_info`, para o `Formatter` reutilizar
        # o `exc_text` já sanitizado (ele só formata o traceback se `exc_text`
        # estiver vazio).
        if record.exc_info:
            record.exc_text = self._redact(
                "".join(traceback.format_exception(*record.exc_info))
            )
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = self._redact(record.exc_text)
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