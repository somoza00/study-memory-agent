"""Testes do logging estruturado: redação de segredos nas mensagens de log."""

from __future__ import annotations

import logging

from app.core.logging import SecretRedactionFilter


def test_secret_redaction_filter_strips_known_secret() -> None:
    record = logging.LogRecord(
        name="app.services.memory_service",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="falha ao chamar OpenAI com a chave sk-supersecret",
        args=(),
        exc_info=None,
    )

    SecretRedactionFilter(["sk-supersecret"]).filter(record)

    assert "sk-supersecret" not in record.msg
    assert "***" in record.msg


def test_redaction_is_noop_when_no_secret_in_message() -> None:
    record = logging.LogRecord(
        name="app", level=logging.INFO, pathname=__file__, lineno=1,
        msg="memória persistida com sucesso", args=(), exc_info=None,
    )

    assert SecretRedactionFilter(["sk-nunca-aparece"]).filter(record) is True
    assert record.msg == "memória persistida com sucesso"


def _record_with_exception(secret: str) -> logging.LogRecord:
    """LogRecord de `logger.exception` cuja mensagem da exceção contém o secret."""
    import sys

    try:
        raise ValueError(f"Incorrect API key provided: {secret}")
    except ValueError:
        exc_info = sys.exc_info()
    return logging.LogRecord(
        name="app.api.routers.chat",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="chat falhou com erro não-OpenAI",
        args=(),
        exc_info=exc_info,
    )


def test_redaction_covers_exception_traceback() -> None:
    """Regressão: `logger.exception` não pode vazar a chave pelo traceback.

    O handler formata o traceback DEPOIS dos filters, então redigir só a
    mensagem deixava a chave aparecer na linha "ValueError: ..." do traceback
    (o SDK da OpenAI ecoa a chave nos erros de autenticação).
    """
    secret = "SEGREDO-DE-TESTE-TRACEBACK-0001"
    record = _record_with_exception(secret)

    SecretRedactionFilter([secret]).filter(record)

    formatted = logging.Formatter().format(record)
    assert secret not in formatted
    assert "***" in formatted
    # O traceback continua no log — só o valor do segredo sai.
    assert "ValueError" in formatted


def test_redaction_covers_preexisting_exc_text() -> None:
    """`exc_text` já formatado (outro handler) também precisa ser redigido."""
    secret = "SEGREDO-DE-TESTE-EXCTEXT-0002"
    record = logging.LogRecord(
        name="app",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="falhou",
        args=(),
        exc_info=None,
    )
    record.exc_text = f"Traceback (most recent call last):\nValueError: {secret}"

    SecretRedactionFilter([secret]).filter(record)

    assert secret not in logging.Formatter().format(record)
