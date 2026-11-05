"""Restaura una copia de origen confiable en PostgreSQL local vacío y la verifica."""

import argparse
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from time import monotonic
from typing import TypedDict
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import URL

from scripts.respaldo import esquema
from scripts.respaldo.respaldar import ErrorRespaldo, conexion_pg, consulta, ejecutar, ejecutar_dump, revision_dump


RAIZ = Path(__file__).resolve().parents[2]
TABLAS_CLAVE = {"tenants": 2, "users": 1, "products": 1, "permissions": 1}


class Check(TypedDict):
    name: str
    ok: bool
    details: dict


def revision_codigo(solicitada: str | None = None) -> str:
    config = Config(str(RAIZ / "alembic.ini"))
    config.set_main_option("script_location", str(RAIZ / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    cabezas = scripts.get_heads()
    if len(cabezas) != 1:
        raise ErrorRespaldo("El código debe tener una única cabeza Alembic.")
    if solicitada is None:
        return cabezas[0]
    revisiones = {revision.revision for revision in scripts.walk_revisions()}
    if solicitada not in revisiones:
        raise ErrorRespaldo("La revisión esperada no existe en la cadena de migraciones.")
    return solicitada


def restaurar(archivo: Path, url_destino: str | URL) -> None:
    destino, env = conexion_pg(url_destino, local=True)
    if not archivo.is_file() or not archivo.stat().st_size:
        raise ErrorRespaldo("El archivo de respaldo no existe o está vacío.")
    existentes = consulta(destino, """
        SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspname NOT LIKE 'pg_toast%'
          AND n.nspname NOT LIKE 'pg_temp_%'
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
    """, local=True)
    if existentes != "0":
        raise ErrorRespaldo("La restauración requiere una base local vacía.")
    ejecutar("pg_restore", ["--no-owner", "--no-privileges", "--exit-on-error", "--single-transaction",
                            "--no-password", "--schema=public", "--dbname", destino.database, str(archivo)], env=env)


def _consulta(url: str | URL, sql: str) -> str:
    return consulta(url, sql, local=True)


def _revisiones(url: str | URL) -> list[str]:
    if not _consulta(url, "SELECT to_regclass('public.alembic_version')"):
        return []
    filas = _consulta(url, "SELECT version_num FROM public.alembic_version").splitlines()
    return [fila if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", fila) else "invalida" for fila in filas]


def _revision_del_destino(url: str | URL) -> str:
    revisiones = _revisiones(url)
    if len(revisiones) != 1:
        raise ErrorRespaldo("La copia debe contener una única revisión Alembic.")
    return revision_codigo(revisiones[0])


def _permisos(url: str | URL) -> dict[str, str]:
    if not _consulta(url, "SELECT to_regclass('public.permissions')"):
        return {}
    filas = _consulta(url, "SELECT coalesce(json_object_agg(code, id::text), '{}') FROM public.permissions")
    return json.loads(filas)


@contextmanager
def _base_vacia(url: str | URL):
    destino, _ = conexion_pg(url, local=True)
    nombre = f"fs_verify_{uuid4().hex}"
    _consulta(destino, f'CREATE DATABASE "{nombre}" TEMPLATE template0')
    try:
        yield destino.set(database=nombre, host="127.0.0.1" if destino.host.lower() == "localhost" else destino.host)
    finally:
        # El nombre aleatorio pertenece exclusivamente a esta ejecución.
        _consulta(destino, f'DROP DATABASE "{nombre}"')


@contextmanager
def _referencia(url: str | URL, revision: str):
    # PostgreSQL puede reescribir casts de restricciones al restaurarlas.
    # Ambos lados de la comparación deben pasar por el mismo formato lógico.
    with tempfile.TemporaryDirectory(prefix="fs-esquema-") as temporal:
        copia = Path(temporal) / "referencia.dump"
        with _base_vacia(url) as migrada:
            env = {nombre: valor for nombre, valor in os.environ.items()
                   if not nombre.upper().startswith(("PG", "RAILWAY_")) and nombre != "ALLOW_REMOTE_DB"}
            env.update(APP_ENV="test", DATABASE_URL=migrada.render_as_string(hide_password=False))
            ejecutar(sys.executable, ["-m", "alembic", "-c", str(RAIZ / "alembic.ini"),
                                     "upgrade", revision], env=env, cwd=RAIZ)
            ejecutar_dump(migrada, copia)
        with _base_vacia(url) as referencia:
            restaurar(copia, referencia)
            yield referencia


def comprobar(url: str | URL, *, revision_esperada: str | None = None,
              limpia: str | URL | None = None) -> list[Check]:
    destino, _ = conexion_pg(url, local=True)
    revision = revision_codigo(revision_esperada) if revision_esperada is not None else _revision_del_destino(destino)
    revisiones = _revisiones(destino)
    revision_ok = revisiones == [revision]
    conteos = {}
    for tabla in TABLAS_CLAVE:
        existe = _consulta(destino, f"SELECT to_regclass('public.{tabla}')")
        conteos[tabla] = int(_consulta(destino, f"SELECT count(*) FROM public.{tabla}")) if existe else 0

    checks: list[Check] = [
        {"name": "revision", "ok": revision_ok,
         "details": {"expected": revision, "actual": revisiones[0] if len(revisiones) == 1 else None,
                     "count": len(revisiones)}},
        {"name": "tablas_clave", "ok": all(conteos[tabla] >= minimo for tabla, minimo in TABLAS_CLAVE.items()),
         "details": conteos},
    ]
    if limpia is None:
        with _referencia(destino, revision) as referencia:
            esperados = _permisos(referencia)
    else:
        esperados = _permisos(limpia)
    actuales = _permisos(destino)
    faltan = esperados.keys() - actuales.keys()
    desconocidos = actuales.keys() - esperados.keys()
    incorrectos = sum(actuales[codigo] != esperados[codigo] for codigo in actuales.keys() & esperados.keys())
    checks.append({"name": "permisos", "ok": bool(esperados) and not (faltan or desconocidos or incorrectos),
                   "details": {"expected": len(esperados), "missing": len(faltan),
                               "extra": len(desconocidos), "wrong_id": incorrectos}})
    return checks


def comparar_esquema(url: str | URL, *, revision_esperada: str | None = None,
                     limpia: str | URL | None = None) -> list[str]:
    if limpia is not None:
        return esquema.comparar(url, limpia)
    revision = revision_codigo(revision_esperada) if revision_esperada is not None else _revision_del_destino(url)
    with _referencia(url, revision) as referencia:
        return esquema.comparar(url, referencia)


def _guardar_reporte(path: Path, reporte: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".verificacion-", dir=path.parent) as temporal:
        archivo = Path(temporal) / "reporte.json"
        archivo.write_text(json.dumps(reporte, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        archivo.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archivo", type=Path, required=True)
    parser.add_argument("--destino-env", default="VERIFY_DATABASE_URL")
    parser.add_argument("--revision-esperada", help="Revisión exacta del manifiesto; por defecto se lee del dump")
    parser.add_argument("--reporte", type=Path, required=True)
    args = parser.parse_args(argv)

    inicio = monotonic()
    checks: list[Check] = []
    revision = None
    codigo = "restauracion_fallida"
    etapa = "restauracion"
    try:
        if args.archivo.resolve() == args.reporte.resolve():
            raise ErrorRespaldo("El reporte debe guardarse en un archivo distinto del respaldo.")
        url = os.environ.get(args.destino_env)
        if not url:
            raise ErrorRespaldo("Falta el destino local en la variable de entorno indicada.")
        # Leer el sello del snapshot del dump, no la cabeza de un checkout que
        # puede estar varias migraciones por delante de la base respaldada.
        etapa, codigo = "revision", "verificacion_fallida"
        revision_copia = revision_dump(args.archivo)
        esperada = revision_codigo(args.revision_esperada if args.revision_esperada is not None else revision_copia)
        if revision_copia != esperada:
            raise ErrorRespaldo("La revisión del manifiesto no coincide con la del dump.")
        etapa, codigo = "restauracion", "restauracion_fallida"
        restaurar(args.archivo, url)
        codigo = "verificacion_fallida"
        with _referencia(url, esperada) as limpia:
            checks.extend(comprobar(url, revision_esperada=esperada, limpia=limpia))
            revision = checks[0]["details"]["actual"]
            diferencias = comparar_esquema(url, limpia=limpia)
            checks.append({"name": "esquema", "ok": not diferencias,
                           "details": {"missing": sum(x.startswith("FALTA ") for x in diferencias),
                                       "extra": sum(x.startswith("EXTRA ") for x in diferencias)}})
    except ErrorRespaldo as error:
        print(error)
        checks.append({"name": etapa, "ok": False, "details": {"code": codigo}})
    except (OSError, ValueError):
        print("No se pudo completar la verificación del respaldo.")
        checks.append({"name": etapa, "ok": False, "details": {"code": codigo}})

    ok = bool(checks) and all(check["ok"] for check in checks)
    reporte = {"ok": ok, "duration_seconds": round(monotonic() - inicio, 3),
               "alembic_revision": revision, "checks": checks}
    if args.archivo.resolve() == args.reporte.resolve():
        return 1
    try:
        _guardar_reporte(args.reporte, reporte)
    except OSError:
        print("No se pudo escribir el reporte de verificación.")
        return 1
    print("Verificación aprobada." if ok else "La copia no pasó la verificación.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
