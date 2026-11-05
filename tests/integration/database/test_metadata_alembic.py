"""Regresión de las FK: únicamente PostgreSQL local temporal propio."""
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from src.infrastructure.database.base import Base
from src.infrastructure.database.safety import require_local_database
from src.main import app  # noqa: F401 - registra todos los modelos expuestos por las rutas.


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def local_database():
    value = os.getenv("TEST_PG_URL")
    if not value:
        pytest.skip("Requiere TEST_PG_URL de PostgreSQL local descartable")
    url = make_url(value)
    require_local_database(url, allow_remote=False)
    name = "ps_metadata_qa_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    engine = None
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        target = url.set(database=name)
        engine = create_engine(target)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("PG", "RAILWAY_")) and k != "ALLOW_REMOTE_DB"}
        env.update(APP_ENV="test", DATABASE_URL=target.render_as_string(hide_password=False))

        def migrate(*args):
            result = subprocess.run([sys.executable, "-m", "alembic", *args], env=env,
                                    cwd=ROOT, capture_output=True, text=True, timeout=120)
            assert result.returncode == 0, "Falló el ciclo Alembic sobre PostgreSQL temporal local."

        yield engine, migrate
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}"'))
        admin.dispose()


def _assert_metadata(engine):
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        fk = [item for item in inspect(connection).get_foreign_keys("support_sessions")
              if item["constrained_columns"] == ["approved_by_user_id"]]
        assert fk and fk[0]["name"] == "fk_support_sessions_approved_by_user_id_users"
        assert fk[0]["referred_table"] == "users" and fk[0]["referred_columns"] == ["id"]
        assert fk[0]["options"].get("ondelete") == "SET NULL"
        assert differences == [], [item[0] if isinstance(item, tuple) else "column_diff" for item in differences]


def test_upgrade_head_coincide_con_metadata(local_database):
    engine, migrate = local_database
    migrate("upgrade", "head")
    _assert_metadata(engine)


def test_ciclo_0031_head_conserva_fk_y_metadata(local_database):
    engine, migrate = local_database
    migrate("upgrade", "head")
    migrate("downgrade", "20261109_0031")
    migrate("upgrade", "head")
    _assert_metadata(engine)
