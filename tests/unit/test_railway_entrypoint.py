from unittest.mock import Mock

import pytest

from scripts import railway_entrypoint as entry


def test_fuera_de_railway_no_habilita_conexion_remota(monkeypatch):
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_DB", raising=False)
    monkeypatch.setattr("sys.argv", ["entry", "prepare"])
    with pytest.raises(RuntimeError, match="requiere un entorno Railway"):
        entry.main()
    assert "ALLOW_REMOTE_DB" not in entry.os.environ


def test_railway_habilita_solo_el_proceso_de_despliegue(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "entorno-prueba")
    monkeypatch.setenv("ALLOW_REMOTE_DB", "0")
    monkeypatch.setattr("sys.argv", ["entry", "prepare"])
    monkeypatch.setattr(entry.os, "chdir", Mock())
    prepare = Mock()
    monkeypatch.setattr(entry, "preparar", prepare)
    entry.main()
    assert entry.os.environ["ALLOW_REMOTE_DB"] == "1"
    prepare.assert_called_once_with()


def test_el_argumento_anterior_ya_no_autoriza_migraciones(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "entorno-prueba")
    monkeypatch.delenv("ALLOW_REMOTE_DB", raising=False)
    monkeypatch.setattr("sys.argv", ["entry", "prepare", "--reconciliar-sin-respaldo"])
    prepare = Mock()
    monkeypatch.setattr(entry, "preparar", prepare)
    with pytest.raises(SystemExit) as exc:
        entry.main()
    assert exc.value.code == 2
    prepare.assert_not_called()
    assert "ALLOW_REMOTE_DB" not in entry.os.environ
