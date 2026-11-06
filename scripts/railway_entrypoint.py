"""Migraciones y arranque de la API en Railway."""

import argparse
import os
import re
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

ROOT = Path(__file__).resolve().parents[1]


def _database_identity(value: str) -> tuple:
    url = make_url(value)
    if os.getenv("PGHOSTADDR") or os.getenv("PGSERVICE"):
        raise ValueError("Destino ambiguo para migraciones.")
    if url.get_backend_name() != "postgresql" or any(
        name.lower() in {"host", "hostaddr", "port", "service", "user", "dbname", "database"} for name in url.query
    ):
        raise ValueError("Destino ambiguo para migraciones.")
    host = (url.host or "").lower().rstrip(".")
    if not host or not url.database:
        raise ValueError("Destino ambiguo para migraciones.")
    direct = re.fullmatch(r"db\.([a-z0-9-]+)\.supabase\.co", host)
    if direct:
        return "supabase", direct[1], url.database
    if host.endswith(".pooler.supabase.com"):
        _, separator, project = (url.username or "").rpartition(".")
        if not separator or not re.fullmatch(r"[a-z0-9-]+", project):
            raise ValueError("Falta referencia de proyecto para el pooler.")
        return "supabase", project, url.database
    return "postgresql", host, url.port or int(os.getenv("PGPORT", "5432")), url.database


def _migration_database_url(application_url: str) -> str:
    migration_url = os.getenv("MIGRATION_DATABASE_URL", "").strip()
    if not migration_url:
        return application_url
    try:
        matches = _database_identity(application_url) == _database_identity(migration_url)
    except (ArgumentError, ValueError, TypeError):
        matches = False
    if not matches:
        raise RuntimeError(
            "config_invalid: MIGRATION_DATABASE_URL y DATABASE_URL deben apuntar a la misma base de datos."
        ) from None
    return migration_url


def _bloquear_migraciones(connection) -> None:
    # Bloqueo transaccional para compartir la decisión con el pre-deploy y los
    # posibles arranques simultáneos. El commit o rollback lo libera.
    connection.execute(text("SET LOCAL lock_timeout = '30s'"))
    connection.execute(text("SELECT pg_advisory_xact_lock(98462032)"))


def preparar() -> None:
    from src.infrastructure.config.settings import settings
    from src.infrastructure.database.safety import require_environment_match, require_local_database

    require_environment_match(settings.app_env, settings.database_url, settings.production_db_host)
    require_local_database(settings.database_url)
    migration_url = _migration_database_url(settings.database_url)
    require_environment_match(settings.app_env, migration_url, settings.production_db_host)
    require_local_database(migration_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("La configuración de Alembic no tiene una revisión cabeza.")

    # El servidor conserva DATABASE_URL. Alembic usa la conexión de migración
    # y mantiene el bloqueo hasta que termina la transacción.
    engine = create_engine(migration_url)
    try:
        with engine.begin() as connection:
            _bloquear_migraciones(connection)
            versions = MigrationContext.configure(connection).get_current_heads()
            if len(versions) > 1:
                raise RuntimeError("La base registra múltiples revisiones; se requiere una revisión manual.")
            if versions == (head,):
                return

            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fase", choices=("prepare", "serve"))
    args = parser.parse_args()
    if not os.environ.get("RAILWAY_ENVIRONMENT_ID"):
        raise RuntimeError("Este punto de entrada requiere un entorno Railway; en local use las herramientas habituales.")
    os.chdir(ROOT)
    if args.fase == "prepare":
        os.environ["ALLOW_REMOTE_DB"] = "1"
        preparar()
    else:
        from scripts.iniciar_servidor import main as iniciar

        iniciar()


if __name__ == "__main__":
    main()
