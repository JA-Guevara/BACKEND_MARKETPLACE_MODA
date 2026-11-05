import subprocess
from unittest.mock import Mock

import pytest

from scripts import railway_entrypoint as entry


@pytest.mark.parametrize("version", [None, "20261108_0028", "20261109_0031"])
def test_cadenas_validas_migran_sin_reconciliar(monkeypatch, version):
    monkeypatch.setattr(entry, "_version_actual", lambda: version)
    run = Mock()
    monkeypatch.setattr(entry.subprocess, "run", run)
    entry.preparar(True)
    run.assert_called_once_with([entry.sys.executable, "-m", "alembic", "upgrade", "head"], check=True)


def test_sello_fantasma_no_se_estampa_sin_autorizacion(monkeypatch):
    monkeypatch.setattr(entry, "_version_actual", lambda: "20261108_0030")
    run = Mock()
    monkeypatch.setattr(entry.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="reconciliacion autorizada"):
        entry.preparar()
    run.assert_not_called()


def test_autorizacion_ejecuta_runner_atomico_sin_respaldo(monkeypatch):
    monkeypatch.setattr(entry, "_version_actual", lambda: "20261108_0030")
    run = Mock()
    monkeypatch.setattr(entry.subprocess, "run", run)
    entry.preparar(True)
    run.assert_called_once_with([entry.sys.executable, "-m", "scripts.reconciliar_produccion",
                                "--aplicar", "--sin-respaldo"], check=True)


def test_fallo_de_reconciliacion_detiene_despliegue(monkeypatch):
    monkeypatch.setattr(entry, "_version_actual", lambda: "20261108_0030")
    run = Mock(side_effect=subprocess.CalledProcessError(1, "runner"))
    monkeypatch.setattr(entry.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        entry.preparar(True)
    assert run.call_count == 1


def test_fuera_de_railway_no_habilita_conexion_remota(monkeypatch):
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_DB", raising=False)
    monkeypatch.setattr(entry.sys, "argv", ["entry", "prepare"])
    with pytest.raises(RuntimeError, match="requiere un entorno Railway"):
        entry.main()
    assert "ALLOW_REMOTE_DB" not in entry.os.environ


def test_railway_habilita_solo_el_proceso_de_despliegue(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "entorno-prueba")
    monkeypatch.setenv("ALLOW_REMOTE_DB", "0")
    monkeypatch.setattr(entry.sys, "argv", ["entry", "prepare", "--reconciliar-sin-respaldo"])
    monkeypatch.setattr(entry.os, "chdir", Mock())
    prepare = Mock()
    monkeypatch.setattr(entry, "preparar", prepare)
    entry.main()
    assert entry.os.environ["ALLOW_REMOTE_DB"] == "1"
    prepare.assert_called_once_with(True)
