"""Testes de `Settings` e da configuração de observabilidade.

O limiar do recall era fixo no código (0.7), calibrado para os embeddings da
OpenAI; com o modelo local (MiniLM) metade dos acertos ficava fora do corte.
Estes testes fixam o contrato: default por provedor, override por env e vazio =
default.
"""

from __future__ import annotations

from unittest.mock import patch

from app.core.config import Settings
from app.services.observability import configure_langfuse_otel


# --- Limiar do recall ---


def test_recall_threshold_defaults_to_openai_value() -> None:
    assert Settings(embedding_provider="openai").recall_score_threshold == 0.7


def test_recall_threshold_defaults_lower_for_local_embeddings() -> None:
    """Modelo local tem scores mais baixos: default precisa ser menor."""
    assert Settings(embedding_provider="local").recall_score_threshold == 0.55


def test_recall_threshold_accepts_env_override(monkeypatch) -> None:
    monkeypatch.setenv("RECALL_MIN_SCORE", "0.42")
    assert Settings(_env_file=None).recall_score_threshold == 0.42


def test_blank_recall_threshold_falls_back_to_provider_default(monkeypatch) -> None:
    """`RECALL_MIN_SCORE=` vazio no .env não quebra a validação: usa o default."""
    monkeypatch.setenv("RECALL_MIN_SCORE", "")
    cfg = Settings(_env_file=None, embedding_provider="local")
    assert cfg.recall_min_score is None
    assert cfg.recall_score_threshold == 0.55


def test_recall_limit_defaults_to_five() -> None:
    assert Settings().recall_limit == 5


def test_recall_scope_defaults_to_all_sessions() -> None:
    """Escopo default "all": o frontend gera sessão nova a cada reload, então com
    escopo por sessão o agente esquecia tudo o que o usuário estudou antes."""
    assert Settings().recall_scope == "all"


def test_recall_scope_accepts_session_override(monkeypatch) -> None:
    monkeypatch.setenv("RECALL_SCOPE", "session")
    assert Settings(_env_file=None).recall_scope == "session"


# --- Observabilidade ---


def test_tracing_is_off_by_default() -> None:
    """Sem Langfuse no ar, exportar gera ruído/timeout: default é desligado."""
    assert Settings().langfuse_enabled is False


def test_disabled_tracing_does_not_install_exporter() -> None:
    with patch("app.services.observability.trace.set_tracer_provider") as set_provider:
        configure_langfuse_otel(Settings(langfuse_enabled=False))

    set_provider.assert_not_called()


def test_enabled_tracing_installs_exporter() -> None:
    with patch("app.services.observability.trace.set_tracer_provider") as set_provider:
        configure_langfuse_otel(Settings(langfuse_enabled=True))

    set_provider.assert_called_once()
