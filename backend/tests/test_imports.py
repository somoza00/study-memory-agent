"""Smoke test: prova que o pacote backend importa sem erros de estrutura."""

import pkgutil

import app


def test_all_backend_modules_importable() -> None:
    """Caminha por todos os módulos do pacote app e tenta importá-los."""
    failed: list[str] = []
    for mod in pkgutil.walk_packages(app.__path__, app.__name__ + "."):
        try:
            __import__(mod.name)
        except Exception as exc:  # noqa: BLE001 - smoke test de scaffold
            failed.append(f"{mod.name}: {exc!r}")
    assert not failed, "Falha ao importar módulos:\n" + "\n".join(failed)
