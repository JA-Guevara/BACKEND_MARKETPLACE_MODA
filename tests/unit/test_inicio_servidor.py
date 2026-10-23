import subprocess
from unittest.mock import Mock

import pytest

from scripts import iniciar_servidor


def test_no_inicia_uvicorn_si_falla_la_migracion(monkeypatch):
    migrate = Mock(side_effect=subprocess.CalledProcessError(1, "alembic"))
    execute = Mock()
    monkeypatch.setattr(iniciar_servidor.os, "chdir", Mock())
    monkeypatch.setattr(iniciar_servidor.subprocess, "run", migrate)
    monkeypatch.setattr(iniciar_servidor.os, "execv", execute)
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(subprocess.CalledProcessError):
        iniciar_servidor.main()
    execute.assert_not_called()


def test_migra_antes_de_crear_workers_y_conserva_configuracion(monkeypatch):
    calls = []
    monkeypatch.setattr(iniciar_servidor.os, "chdir", Mock())
    monkeypatch.setattr(iniciar_servidor.subprocess, "run",
                        lambda command, **kwargs: calls.append(("migrate", command, kwargs)))
    monkeypatch.setattr(iniciar_servidor.os, "execv",
                        lambda executable, command: calls.append(("serve", command)))
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("WEB_CONCURRENCY", "3")
    iniciar_servidor.main()
    assert calls[0] == ("migrate", [iniciar_servidor.sys.executable, "-m", "alembic", "upgrade", "head"], {"check": True})
    assert calls[1][0] == "serve"
    assert calls[1][1][-4:] == ["--port", "8080", "--workers", "3"]


@pytest.mark.parametrize("port,workers", [("0", "2"), ("65536", "2"), ("8000", "0")])
def test_configuracion_invalida_no_toca_la_base(monkeypatch, port, workers):
    migrate = Mock()
    monkeypatch.setattr(iniciar_servidor.subprocess, "run", migrate)
    monkeypatch.setenv("PORT", port)
    monkeypatch.setenv("WEB_CONCURRENCY", workers)
    with pytest.raises(ValueError):
        iniciar_servidor.main()
    migrate.assert_not_called()
