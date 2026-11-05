from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import UUID

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa


def test_colision_057_aborta_antes_de_crear_tabla_o_modificar_permisos():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261110_0032_platform_backups.py"
    spec = spec_from_file_location("migracion_0032_prueba", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    meta = sa.MetaData()
    permisos = sa.Table(
        "permissions", meta,
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("code", sa.String(), unique=True),
        sa.Column("scope", sa.String()), sa.Column("module", sa.String()),
    )
    meta.create_all(engine)
    existing = UUID("20000000-0000-0000-0000-000000000057")
    with engine.begin() as conn:
        conn.execute(permisos.insert().values(id=existing, code="permiso.anterior", scope="tenant", module="users"))
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            with pytest.raises(RuntimeError, match="platform.ops.read.*conflicto"):
                migration.upgrade()
        assert conn.execute(sa.select(permisos)).one()._mapping == {
            "id": existing, "code": "permiso.anterior", "scope": "tenant", "module": "users",
        }
        assert not sa.inspect(conn).has_table("platform_backups")
    engine.dispose()
