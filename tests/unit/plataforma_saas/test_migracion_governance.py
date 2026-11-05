"""0029 aislada: el historial 0001 contiene JSONB exclusivo de PostgreSQL.

Este fixture representa las tablas previas que toca 0029; no afirma que toda
la cadena histórica sea portable a SQLite.
"""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_0029_sqlite_upgrade_downgrade_upgrade_preserva_uuid_y_permisos():
    spec = importlib.util.spec_from_file_location("governance_migration_qa",
        Path(__file__).resolve().parents[3] / "alembic/versions/20261104_0029_platform_governance.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    def stamps():
        return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]
    sa.Table("users", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    sa.Table("tenants", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    sa.Table("support_sessions", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    roles = sa.Table("roles", metadata, sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid()), sa.Column("code", sa.String()), sa.Column("name", sa.String()),
        sa.Column("description", sa.String()), sa.Column("is_system", sa.Boolean()),
        sa.Column("is_active", sa.Boolean()), *stamps())
    sa.Table("permissions", metadata, sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String()), sa.Column("name", sa.String()), sa.Column("description", sa.String()),
        sa.Column("module", sa.String()), sa.Column("scope", sa.String()),
        sa.Column("is_active", sa.Boolean()), *stamps())
    sa.Table("role_permissions", metadata, sa.Column("role_id", sa.Uuid(), primary_key=True),
        sa.Column("permission_id", sa.Uuid(), primary_key=True))
    plans = sa.Table("plans", metadata, sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("code", sa.String()))
    sa.Table("plan_features", metadata, sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("plan_id", sa.Uuid()), sa.Column("feature_code", sa.String()), sa.Column("enabled", sa.Boolean()))
    metadata.create_all(engine)
    try:
        with engine.begin() as connection:
            now = datetime.now(timezone.utc)
            connection.execute(roles.insert().values(id=migration.ROLE_PLATFORM_ADMIN, code="platform_admin",
                name="Plataforma", is_system=True, is_active=True, created_at=now, updated_at=now))
            connection.execute(plans.insert(), [{"id": uuid4(), "code": code} for code in ("BASICO", "PROFESIONAL")])
            def run(direction):
                with Operations.context(MigrationContext.configure(connection)):
                    getattr(migration, direction)()
            run("upgrade")
            assert connection.scalar(sa.text("SELECT count(*) FROM platform_modules")) == 12
            assert connection.scalar(sa.text("SELECT count(*) FROM roles WHERE audience='PLATFORM'")) == 4
            permissions = sa.Table("permissions", sa.MetaData(), autoload_with=connection)
            ids = list(connection.scalars(sa.select(permissions.c.id)))
            assert UUID("20000000-0000-0000-0000-000000000047").hex in {str(value).replace("-", "") for value in ids}
            assert connection.scalar(sa.text("SELECT count(*) FROM role_permissions WHERE role_id=:id"),
                {"id": migration.ROLE_PLATFORM_ADMIN.hex}) == 6
            run("downgrade")
            assert "platform_modules" not in sa.inspect(connection).get_table_names()
            assert connection.scalar(sa.text("SELECT count(*) FROM roles")) == 1
            run("upgrade")
            assert connection.scalar(sa.text("SELECT count(*) FROM platform_modules")) == 12
    finally:
        engine.dispose()
