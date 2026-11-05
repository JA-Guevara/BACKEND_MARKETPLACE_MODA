"""Preparación y arranque del despliegue autorizado en Railway.

La autorización remota se limita a este punto de entrada y sus subprocesos;
no modifica el .env local. El sello fantasma solo se repara si el comando
incluye la excepción sin respaldo autorizada por el usuario.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def _version_actual() -> str | None:
    from sqlalchemy import create_engine, inspect, text
    from src.infrastructure.config.settings import settings
    from src.infrastructure.database.safety import require_local_database

    require_local_database(settings.database_url)
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_table("alembic_version"):
                return None
            versions = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
            if len(versions) > 1:
                raise RuntimeError("La base registra multiples revisiones; no se reconciliara automaticamente.")
            return versions[0] if versions else None
    finally:
        engine.dispose()


def preparar(sin_respaldo: bool = False) -> None:
    version = _version_actual()
    if version == "20261108_0030":
        if not sin_respaldo:
            raise RuntimeError("El sello fantasma requiere reconciliacion autorizada; no se iniciara la API.")
        print("Reconciliando el sello antiguo con la autorizacion sin respaldo del 05/11/2026.", flush=True)
        subprocess.run([sys.executable, "-m", "scripts.reconciliar_produccion",
                        "--aplicar", "--sin-respaldo"], check=True)
    else:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fase", choices=("prepare", "serve"))
    parser.add_argument("--reconciliar-sin-respaldo", action="store_true")
    args = parser.parse_args()
    if args.fase == "serve" and args.reconciliar_sin_respaldo:
        parser.error("La reconciliacion solo se permite en prepare")
    if not os.environ.get("RAILWAY_ENVIRONMENT_ID"):
        raise RuntimeError("Este punto de entrada requiere un entorno Railway; en local use las herramientas habituales.")
    os.chdir(Path(__file__).resolve().parents[1])
    os.environ["ALLOW_REMOTE_DB"] = "1"
    if args.fase == "prepare":
        preparar(args.reconciliar_sin_respaldo)
    else:
        from scripts.iniciar_servidor import main as iniciar
        iniciar()


if __name__ == "__main__":
    main()
