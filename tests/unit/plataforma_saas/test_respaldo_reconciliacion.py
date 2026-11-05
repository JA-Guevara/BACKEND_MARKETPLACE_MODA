"""La puerta de escritura rechaza archivos que no son respaldos restaurables."""
from datetime import datetime, timezone
import os
import subprocess
from types import SimpleNamespace

import pytest

from scripts import reconciliar_produccion as runner


VALID_TOC = """; Archive created by pg_dump
215; 1259 24576 TABLE public alembic_version postgres
3010; 0 24576 TABLE DATA public alembic_version postgres
"""


@pytest.fixture
def backup(tmp_path, monkeypatch):
    path = tmp_path / "respaldo.dump"
    path.write_bytes(b"PGDMP")
    monkeypatch.setattr(runner.shutil, "which", lambda name: "pg_restore")
    return path


@pytest.mark.parametrize("toc", [VALID_TOC])
def test_backup_legible_con_sello_y_datos_es_aceptado(backup, monkeypatch, toc):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=toc)

    monkeypatch.setattr(runner.subprocess, "run", run)
    runner._validar_backup(backup)
    assert calls[0][0] == ["pg_restore", "--list", str(backup.resolve())]
    assert calls[0][1]["timeout"] == 60
    assert calls[0][1].get("shell", False) is False


@pytest.mark.parametrize("toc", [
    "",
    "215; 1259 24576 TABLE private alembic_version postgres\n",
    "215; 1259 24576 TABLE public alembic_version postgres\n",
    "3010; 0 24576 TABLE DATA public alembic_version postgres\n",
    "; TABLE public alembic_version TABLE DATA public alembic_version\n",
])
def test_backup_sin_tabla_y_datos_del_sello_es_rechazado(backup, monkeypatch, toc):
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=toc))
    with pytest.raises(SystemExit, match="public.alembic_version"):
        runner._validar_backup(backup)


def test_archivo_invalido_rechazado_por_pg_restore(backup, monkeypatch):
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stdout=""))
    with pytest.raises(SystemExit, match="rechazo el respaldo"):
        runner._validar_backup(backup)


@pytest.mark.parametrize("error", [OSError("no executable"), subprocess.TimeoutExpired("pg_restore", 60)])
def test_fallo_o_timeout_cierra_la_puerta_de_escritura(backup, monkeypatch, error):
    def run(*args, **kwargs):
        raise error
    monkeypatch.setattr(runner.subprocess, "run", run)
    with pytest.raises(SystemExit, match="No se pudo validar"):
        runner._validar_backup(backup)


def test_pg_restore_ausente(backup, monkeypatch):
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="No se encontro pg_restore"):
        runner._validar_backup(backup)


def test_respaldo_viejo_es_rechazado_antes_de_pg_restore(backup):
    timestamp = datetime.now(timezone.utc).timestamp() - 25 * 3600
    os.utime(backup, (timestamp, timestamp))
    with pytest.raises(SystemExit, match="mas de 24 horas"):
        runner._validar_backup(backup)


@pytest.mark.parametrize("kind", ["missing", "empty", "directory"])
def test_archivo_inexistente_vacio_o_directorio_rechazado(tmp_path, kind):
    path = tmp_path / "respaldo.dump"
    if kind == "empty":
        path.touch()
    elif kind == "directory":
        path.mkdir()
    with pytest.raises(SystemExit, match="no existe o esta vacio"):
        runner._validar_backup(path)


def test_falta_ruta_de_respaldo():
    with pytest.raises(SystemExit, match="se requiere --backup-archivo"):
        runner._validar_backup(None)
