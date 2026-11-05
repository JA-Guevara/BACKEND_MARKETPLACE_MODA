"""Puerta de migraciones y arranque de la API en Railway."""

import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]


def _bloquear_migraciones(connection) -> None:
    # Bloqueo transaccional para compartir la decisión con el pre-deploy y los
    # posibles arranques simultáneos. El commit o rollback lo libera.
    connection.execute(text("SET LOCAL lock_timeout = '30s'"))
    connection.execute(text("SELECT pg_advisory_xact_lock(98462032)"))


def _copia_verificada(connection, revision: str | None, now: datetime) -> bool:
    if revision is None or not inspect(connection).has_table("platform_backups"):
        return False
    return bool(connection.scalar(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM platform_backups
                 WHERE verify_status = 'ok'
                   AND alembic_revision = :revision
                   AND finished_at > :minimum AND finished_at <= :now
            )
        """),
        {"revision": revision, "minimum": now - timedelta(hours=24), "now": now},
    ))


def _registrar_excepcion(connection, revision: str | None, head: str, fecha: str) -> None:
    from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel

    connection.execute(AuditEventModel.__table__.insert().values(
        tenant_id=None,
        actor_user_id=None,
        action="platform.migration_without_backup",
        entity_type="database",
        description="Migración autorizada sin respaldo verificado.",
        metadata={"revision_previa": revision, "revision_nueva": head, "fecha_autorizada": fecha},
    ))


def preparar() -> None:
    from src.infrastructure.config.settings import settings
    from src.infrastructure.database.safety import require_environment_match, require_local_database

    require_environment_match(settings.app_env, settings.database_url, settings.production_db_host)
    require_local_database(settings.database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("La configuración de Alembic no tiene una revisión cabeza.")

    excepcion = None
    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as connection:
            _bloquear_migraciones(connection)
            versions = MigrationContext.configure(connection).get_current_heads()
            if len(versions) > 1:
                raise RuntimeError("La base registra múltiples revisiones; se requiere una revisión manual.")
            revision = versions[0] if versions else None
            if revision == head:
                return

            now = datetime.now(timezone.utc)
            fecha = now.astimezone(ZoneInfo("America/La_Paz")).date().isoformat()
            if not _copia_verificada(connection, revision, now):
                if os.environ.get("MIGRACION_SIN_RESPALDO_AUTORIZADA") != fecha:
                    raise RuntimeError(
                        "backup_gate_blocked: la revisión actual requiere una copia verificada "
                        "de menos de 24 h o una autorización con la fecha de hoy en Bolivia."
                    )
                excepcion = fecha

            # Alembic usa la misma conexión que evaluó el respaldo y tomó el
            # bloqueo. La bitácora de excepción se confirma junto a la migración.
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            if excepcion:
                _registrar_excepcion(connection, revision, head, excepcion)
    finally:
        engine.dispose()

    if excepcion:
        print(f"backup_gate_exception: migración sin respaldo autorizada para {excepcion}.", flush=True)


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
