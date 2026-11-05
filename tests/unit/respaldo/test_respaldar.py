from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.respaldo import respaldar


def test_rechaza_salida_en_repo_o_en_workspace(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: ruta-de-worktree")
    with pytest.raises(respaldar.ErrorRespaldo, match="fuera de los repositorios"):
        respaldar.validar_salida(repo / "subdir" / "copias")
    with pytest.raises(respaldar.ErrorRespaldo, match="fuera de los repositorios"):
        respaldar.validar_salida(tmp_path / "Primer Examen Parcial" / "copias")
    assert respaldar.validar_salida(tmp_path / "copias") == tmp_path / "copias"


def test_dump_envia_contrasena_solo_por_entorno(tmp_path, monkeypatch):
    destino = tmp_path / "copia.dump"
    llamadas = []

    def ejecutar(args, *, env, **kwargs):
        llamadas.append((args, env))
        destino.write_bytes(b"PGDMP")
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setenv("PGHOSTADDR", "203.0.113.5")
    monkeypatch.setenv("PGSERVICE", "servicio-ajeno")
    monkeypatch.setenv("BACKUP_DATABASE_URL", "postgresql://otra-clave@example.invalid/backup")
    monkeypatch.setattr(respaldar.subprocess, "run", ejecutar)
    assert respaldar.ejecutar_dump("postgresql://rol:p%40ss@example.invalid:5432/fs?sslmode=require",
                                 destino) == destino
    args, env = llamadas[0]
    assert args == ["pg_dump", "-Fc", "-n", "public", "--no-owner", "--no-privileges", "-w", "-f", str(destino)]
    assert env["PGPASSWORD"] == "p@ss"
    assert env["PGHOST"] == "example.invalid"
    assert env["PGSSLMODE"] == "require"
    assert not ({"PGHOSTADDR", "PGSERVICE", "BACKUP_DATABASE_URL"} & env.keys())


def test_pg_dump_anterior_al_servidor_aborta(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DATABASE_URL", "postgresql://rol@127.0.0.1/fs")
    monkeypatch.setattr(respaldar, "version_servidor", lambda url: 180001)
    llamadas = []

    def ejecutar(herramienta, args, **kwargs):
        llamadas.append((herramienta, args))
        return "pg_dump (PostgreSQL) 17.7"

    monkeypatch.setattr(respaldar, "ejecutar", ejecutar)
    salida = tmp_path / "copias"
    assert respaldar.main(["--salida", str(salida), "--tipo", "manual"]) == 1
    assert llamadas == [("pg_dump", ["--version"])]
    assert not salida.exists()


@pytest.mark.parametrize("modo", ["disable", "allow", "prefer"])
def test_respaldo_remoto_requiere_tls(modo):
    _, env = respaldar.conexion_pg("postgresql://rol@db.example.invalid/fs")
    assert env["PGSSLMODE"] == "require"
    with pytest.raises(respaldar.ErrorRespaldo, match="requiere TLS"):
        respaldar.conexion_pg(f"postgresql://rol@db.example.invalid/fs?sslmode={modo}")


def test_manifiesto_solo_guarda_campos_permitidos(tmp_path):
    archivo = tmp_path / "copia.dump.age"
    archivo.write_bytes(b"cifrado")
    meta = dict(tipo="manual", inicio="2026-11-05T00:00:00+00:00", fin="2026-11-05T00:01:00+00:00",
                revision_alembic="20261109_0031", version_servidor=180001,
                host_redactado="db.example.invalid", user="usuario-no-publicable", password="clave-no-publicable")
    manifiesto = respaldar.manifiesto(archivo, meta)
    assert set(manifiesto) == {"archivo", "bytes", "sha256", "tipo", "inicio", "fin", "revision_alembic",
                               "version_servidor", "host_redactado"}
    assert manifiesto["bytes"] == 7
    assert len(manifiesto["sha256"]) == 64
    assert "no-publicable" not in repr(manifiesto)


def test_revision_sale_de_los_datos_del_dump(monkeypatch):
    monkeypatch.setattr(respaldar, "ejecutar", lambda *a, **kw:
                        "COPY public.alembic_version (version_num) FROM stdin;\n20261109_0031\n\\.\n")
    assert respaldar.revision_dump(Path("copia.dump")) == "20261109_0031"
    monkeypatch.setattr(respaldar, "ejecutar", lambda *a, **kw:
                        "COPY public.alembic_version (version_num) FROM stdin;\nprimera\nsegunda\n\\.\n")
    with pytest.raises(respaldar.ErrorRespaldo, match="única revisión"):
        respaldar.revision_dump(Path("copia.dump"))


def test_fallo_de_cifrado_limpia_temporal_y_no_publica_copia(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DATABASE_URL", "postgresql://rol@127.0.0.1/fs")
    monkeypatch.setattr(respaldar, "version_servidor", lambda url: 180001)
    monkeypatch.setattr(respaldar, "validar_version_dump", lambda version: None)
    monkeypatch.setattr(respaldar, "revision_dump", lambda path: "20261109_0031")

    def dump(url, path):
        path.write_bytes(b"PGDMP")
        return path

    def cifrado_fallido(*args):
        raise respaldar.ErrorRespaldo("age falló")

    monkeypatch.setattr(respaldar, "ejecutar_dump", dump)
    monkeypatch.setattr(respaldar, "cifrar", cifrado_fallido)
    args = ["--salida", str(tmp_path), "--tipo", "manual", "--age-recipient", "age1prueba"]
    assert respaldar.main(args) == 1
    assert list(tmp_path.iterdir()) == []
