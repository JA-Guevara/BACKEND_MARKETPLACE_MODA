"""Corrige el sello Alembic divergente de produccion y aplica la reconciliacion.

Uso seguro (solo lectura, muestra el plan):

    python scripts/reconciliar_produccion.py

Aplicar en produccion (exige un pg_dump reciente):

    python scripts/reconciliar_produccion.py --aplicar --backup-archivo RUTA\\respaldo.dump

El script:
1. Verifica que la version actual sea ``20261108_0030`` (sello fantasma de
   produccion), ``20261108_0028`` (cabeza real anterior) o ``20261109_0031``.
2. En una sola transaccion, cambia el sello a ``20261108_0028`` y ejecuta
   ``alembic upgrade head``. Si la migracion falla, la transaccion revierte el
   sello y los DDL.
3. Verifica que el esquema haya quedado completo y que la version final sea
   ``20261109_0031``.

No imprime cadenas de conexion, credenciales ni tokens.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import os
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from src.infrastructure.config.settings import settings  # noqa: E402


REVISION_FANTASMA = "20261108_0030"
REVISION_BASE = "20261108_0028"
REVISION_OBJETIVO = "20261109_0031"

TABLAS_ESPERADAS = {
    "catalog_template_imports",
    "catalog_templates",
    "report_requests",
    "tenant_payment_methods",
    "upgrade_requests",
    "usage_alerts",
}

COLUMNAS_TENANT = {
    "is_published",
    "published_at",
    "logo_url",
    "banner_url",
    "brand_color",
    "slogan",
    "about",
    "whatsapp",
    "social_links",
    "shipping_policy",
    "seo_title",
    "seo_description",
    "city",
    "is_featured",
}

COLUMNAS_ML = {"artifact", "artifact_bytes", "artifact_sha256"}

PERMISOS_ESPERADOS = {
    "ai_reports.history",
    "ai_reports.use",
    "catalog_templates.write",
    "payment_methods.write",
    "storefront.write",
    "upgrade_requests.manage",
}


def _table_names(connection) -> set[str]:
    return set(inspect(connection).get_table_names())


def _column_names(connection, table: str) -> set[str]:
    if table not in _table_names(connection):
        return set()
    return {column["name"] for column in inspect(connection).get_columns(table)}


def _index_names(connection, table: str) -> set[str]:
    if table not in _table_names(connection):
        return set()
    return {item["name"] for item in inspect(connection).get_indexes(table)}


def _unique_names(connection, table: str) -> set[str]:
    if table not in _table_names(connection):
        return set()
    return {item["name"] for item in inspect(connection).get_unique_constraints(table)}


def _scalar(connection, sql: str, params: dict | None = None):
    return connection.execute(text(sql), params or {}).scalar()


def _preflight(connection) -> dict:
    tables = _table_names(connection)
    tenant_columns = _column_names(connection, "tenants")
    ml_columns = _column_names(connection, "ml_models")
    permissions = set()
    if "permissions" in tables:
        permissions = {
            row[0]
            for row in connection.execute(text("SELECT code FROM permissions")).fetchall()
        }

    catalog_copies_rows = None
    if "_rs_catalog_copies" in tables:
        catalog_copies_rows = _scalar(connection, "SELECT count(*) FROM _rs_catalog_copies")

    ml_rows = None
    if "ml_models" in tables:
        ml_rows = _scalar(connection, "SELECT count(*) FROM ml_models")

    module_duplicates = []
    if "module_permissions" in tables:
        module_duplicates = [
            row[0]
            for row in connection.execute(
                text(
                    "SELECT permission_id FROM module_permissions "
                    "GROUP BY permission_id HAVING count(*) > 1"
                )
            ).fetchall()
        ]

    return {
        "version": _scalar(connection, "SELECT version_num FROM alembic_version"),
        "tablas_faltantes": sorted(TABLAS_ESPERADAS - tables),
        "columnas_tenant_faltantes": sorted(COLUMNAS_TENANT - tenant_columns),
        "columnas_ml_faltantes": sorted(COLUMNAS_ML - ml_columns),
        "ml_models_filas": ml_rows,
        "ml_models_tiene_file_path": "file_path" in ml_columns,
        "permisos_faltantes": sorted(PERMISOS_ESPERADOS - permissions),
        "module_permissions_duplicados": [str(value) for value in module_duplicates],
        "catalog_copies_filas": catalog_copies_rows,
        "report_requests_user_index": (
            "ix_report_requests_user_id" in _index_names(connection, "report_requests")
        ),
        "module_permissions_unique": (
            "uq_module_permissions_permission_id" in _unique_names(connection, "module_permissions")
        ),
    }


def _print_plan(info: dict) -> None:
    print("=== Plan de reconciliacion ===")
    print(f"Version actual: {info['version']}")
    print(f"Version objetivo: {REVISION_OBJETIVO}")
    print(f"Tablas faltantes: {info['tablas_faltantes'] or 'ninguna'}")
    print(f"Columnas de tenants faltantes: {info['columnas_tenant_faltantes'] or 'ninguna'}")
    print(f"Columnas ML faltantes: {info['columnas_ml_faltantes'] or 'ninguna'}")
    print(f"ml_models filas: {info['ml_models_filas']}")
    print(f"ml_models.file_path presente: {info['ml_models_tiene_file_path']}")
    print(f"Permisos faltantes: {info['permisos_faltantes'] or 'ninguno'}")
    print(f"module_permissions duplicados: {info['module_permissions_duplicados'] or 'ninguno'}")
    print(f"_rs_catalog_copies filas: {info['catalog_copies_filas']}")
    print(f"Indice ix_report_requests_user_id: {info['report_requests_user_index']}")
    print(f"Unique uq_module_permissions_permission_id: {info['module_permissions_unique']}")


def _validar_backup(path: Path | None) -> None:
    if path is None:
        raise SystemExit(
            "Para aplicar en una base no local se requiere --backup-archivo con un pg_dump reciente."
        )
    if not path.exists() or path.stat().st_size == 0:
        raise SystemExit(f"El respaldo no existe o esta vacio: {path}")
    age_seconds = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    if age_seconds > 24 * 3600:
        raise SystemExit(f"El respaldo tiene mas de 24 horas: {path}")


def _es_local(engine) -> bool:
    return (engine.url.host or "") in {"127.0.0.1", "localhost", "::1"}


def _verificar_post(connection) -> None:
    info = _preflight(connection)
    problemas = {
        "version": info["version"] != REVISION_OBJETIVO,
        "tablas": bool(info["tablas_faltantes"]),
        "columnas_tenant": bool(info["columnas_tenant_faltantes"]),
        "columnas_ml": bool(info["columnas_ml_faltantes"]),
        "file_path": info["ml_models_tiene_file_path"],
        "permisos": bool(info["permisos_faltantes"]),
        "duplicados_module_permissions": bool(info["module_permissions_duplicados"]),
        "catalog_copies": info["catalog_copies_filas"] is not None,
        "indice_report_user": not info["report_requests_user_index"],
        "unique_module_permissions": not info["module_permissions_unique"],
    }
    fallos = [name for name, failed in problemas.items() if failed]
    if fallos:
        _print_plan(info)
        raise RuntimeError(f"La verificacion posterior fallo: {', '.join(fallos)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aplicar", action="store_true", help="Ejecuta los cambios (sin esto es solo lectura).")
    parser.add_argument("--backup-archivo", type=Path, help="Ruta del pg_dump reciente que respalda la operacion.")
    args = parser.parse_args()

    engine = create_engine(settings.database_url)
    try:
        # El preflight debe cerrar su transaccion antes de escribir: sus SELECT
        # mantienen ACCESS SHARE sobre las tablas y bloquearian el ALTER TABLE
        # de la migracion si se ejecutara en otra conexion del pool.
        with engine.connect() as connection:
            info = _preflight(connection)
            _print_plan(info)
            version_inicial = info["version"]
            connection.rollback()

        if version_inicial not in {REVISION_FANTASMA, REVISION_BASE, REVISION_OBJETIVO}:
            raise SystemExit(
                f"Version inesperada {version_inicial}. Este script solo repara "
                f"{REVISION_FANTASMA} o {REVISION_BASE}."
            )

        if not args.aplicar:
            print("\nDRY RUN: no se escribio nada. Usar --aplicar para ejecutar.")
            return 0

        if not _es_local(engine):
            _validar_backup(args.backup_archivo)
        elif args.backup_archivo is not None:
            _validar_backup(args.backup_archivo)

        print("\nAplicando en una sola transaccion...", flush=True)
        with engine.begin() as connection:
            # Evitar que un lock ajeno deje el despliegue colgado.
            connection.execute(text("SET lock_timeout = '15s'"))
            connection.execute(text("SET statement_timeout = '120s'"))
            version = _scalar(connection, "SELECT version_num FROM alembic_version")
            if version == REVISION_FANTASMA:
                connection.execute(
                    text("UPDATE alembic_version SET version_num = :revision"),
                    {"revision": REVISION_BASE},
                )
                version = REVISION_BASE

            if version not in {REVISION_BASE, REVISION_OBJETIVO}:
                raise RuntimeError(f"Version inesperada dentro de la transaccion: {version}")

            if version != REVISION_OBJETIVO:
                config = Config(str(ROOT / "alembic.ini"))
                config.set_main_option("script_location", str(ROOT / "alembic"))
                config.set_main_option("sqlalchemy.url", str(settings.database_url).replace("%", "%%"))
                config.attributes["connection"] = connection
                print("Ejecutando alembic upgrade head...", flush=True)
                command.upgrade(config, "head")
                print("Alembic upgrade head termino.", flush=True)

            print("Verificando el esquema posterior...", flush=True)
            _verificar_post(connection)
            print("Verificacion posterior OK.", flush=True)

        print("\nOK: esquema reconciliado y version final", REVISION_OBJETIVO)
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
