import subprocess
from unittest.mock import Mock

import pytest

from scripts import iniciar_servidor, railway_entrypoint


@pytest.fixture(autouse=True)
def aislar_entorno_de_arranque(monkeypatch):
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_DB", raising=False)


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


def test_comando_legacy_railway_prepara_antes_de_arrancar_workers(monkeypatch):
    calls = []
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "railway-prueba")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("WEB_CONCURRENCY", "3")
    monkeypatch.setattr(iniciar_servidor.os, "chdir", Mock())

    def preparar(**kwargs):
        assert iniciar_servidor.os.environ["ALLOW_REMOTE_DB"] == "1"
        calls.append(("prepare", kwargs))

    monkeypatch.setattr(railway_entrypoint, "preparar", preparar)
    monkeypatch.setattr(iniciar_servidor.os, "execv",
                        lambda executable, command: calls.append(("serve", command)))
    iniciar_servidor.main()
    assert calls[0] == ("prepare", {"sin_respaldo": True})
    assert calls[1][0] == "serve"
    assert calls[1][1][-4:] == ["--port", "8080", "--workers", "3"]


def test_fallo_en_preparacion_legacy_railway_no_inicia_api(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "railway-prueba")
    monkeypatch.setattr(iniciar_servidor.os, "chdir", Mock())
    monkeypatch.setattr(railway_entrypoint, "preparar",
                        Mock(side_effect=RuntimeError("reconciliacion fallida")))
    execute = Mock()
    monkeypatch.setattr(iniciar_servidor.os, "execv", execute)
    with pytest.raises(RuntimeError, match="reconciliacion fallida"):
        iniciar_servidor.main()
    execute.assert_not_called()


def test_arranque_local_no_habilita_motor_remoto(monkeypatch):
    migrate = Mock(side_effect=subprocess.CalledProcessError(1, "alembic"))
    monkeypatch.setattr(iniciar_servidor.os, "chdir", Mock())
    monkeypatch.setattr(iniciar_servidor.subprocess, "run", migrate)
    with pytest.raises(subprocess.CalledProcessError):
        iniciar_servidor.main()
    assert "ALLOW_REMOTE_DB" not in iniciar_servidor.os.environ


def test_wrapper_serve_conserva_la_preparacion_del_arranque(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "railway-prueba")
    monkeypatch.setattr(railway_entrypoint.sys, "argv", ["entry", "serve"])
    monkeypatch.setattr(iniciar_servidor.os, "chdir", Mock())
    prepare = Mock()
    monkeypatch.setattr(railway_entrypoint, "preparar", prepare)
    execute = Mock()
    monkeypatch.setattr(iniciar_servidor.os, "execv", execute)
    railway_entrypoint.main()
    prepare.assert_called_once_with(sin_respaldo=True)
    execute.assert_called_once()
