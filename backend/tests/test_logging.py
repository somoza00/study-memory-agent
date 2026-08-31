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