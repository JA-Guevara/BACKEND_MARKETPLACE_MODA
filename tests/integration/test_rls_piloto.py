"""RLS real: migración piloto y rol local no dueño, NOSUPERUSER/NOBYPASSRLS."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from src.infrastructure.database.safety import require_local_database
from src.infrastructure.database.session import is_rls_enabled, set_rls_context
from src.shared.context.audit_context import reset_audit_context, set_audit_context

TABLES = ("products", "commerce_orders", "reservations")


def test_rls_enabled_flag(monkeypatch):
    for value, expected in (("true", True), ("1", True), ("false", False)):
        monkeypatch.setenv("RLS_ENABLED", value)
        assert is_rls_enabled() is expected
    monkeypatch.delenv("RLS_ENABLED", raising=False)
    assert is_rls_enabled() is False


def test_set_rls_context_sqlite_safe():
    engine = create_engine("sqlite:///:memory:")
    try:
        with Session(engine) as db:
            set_rls_context(db, tenant_id=uuid4())
            set_rls_context(db, is_platform=True)
    finally:
        engine.dispose()


@pytest.fixture
def pg_pilot(monkeypatch):
    value = os.getenv("TEST_PG_URL")
    if not value:
        pytest.skip("Requiere TEST_PG_URL local y descartable")
    url = make_url(value)
    require_local_database(url, allow_remote=False)
    tag = uuid4().hex
    name, role = "fs_rls_qa_" + tag, "rls_prueba_" + tag
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    engine = None
    a, b = uuid4(), uuid4()
    monkeypatch.setenv("RLS_ENABLED", "false")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
        c.execute(text(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN'))
    try:
        engine = create_engine(url.set(database=name), pool_size=1, max_overflow=0)
        with engine.begin() as c:
            for table in TABLES:
                c.execute(text(f'CREATE TABLE {table} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)'))
                c.execute(text(f'INSERT INTO {table} VALUES (:id, :a), (:other, :b)'),
                          dict(id=uuid4(), other=uuid4(), a=a, b=b))
            file = Path(__file__).resolve().parents[2] / "alembic/versions/20261122_0041_rls_piloto.py"
            spec = importlib.util.spec_from_file_location("qa_real_migration_0041", file)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            with Operations.context(MigrationContext.configure(c)):
                migration.upgrade()
            c.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
            for table in TABLES:
                c.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO "{role}"'))
        yield SimpleNamespace(engine=engine, a=a, b=b, role=role)
    finally:
        if engine:
            engine.dispose()
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
            c.execute(text(f'DROP ROLE "{role}"'))
        admin.dispose()


def app_role(db, world):
    db.execute(text(f'SET LOCAL ROLE "{world.role}"'))
    assert db.scalar(text("SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname=current_user")) is False


def tenant_rows(db, table):
    return db.scalars(text(f"SELECT tenant_id FROM {table}")).all()


def test_empresa_no_ve_ni_modifica_otra_empresa(pg_pilot):
    w = pg_pilot
    for tenant in (w.a, w.b):
        with Session(w.engine) as db:
            app_role(db, w)
            set_rls_context(db, tenant_id=tenant)
            for table in TABLES:
                assert tenant_rows(db, table) == [tenant]
                assert db.execute(text(f"DELETE FROM {table} WHERE tenant_id != :tenant"), {"tenant": tenant}).rowcount == 0


def test_plataforma_ve_todas_las_empresas(pg_pilot):
    w = pg_pilot
    with Session(w.engine) as db:
        app_role(db, w)
        set_rls_context(db, is_platform=True)
        for table in TABLES:
            assert set(tenant_rows(db, table)) == {w.a, w.b}


def test_tienda_publica_fija_contexto_tras_resolver_slug(pg_pilot, monkeypatch):
    from src.infrastructure.security import tenancy
    w = pg_pilot
    monkeypatch.setenv("RLS_ENABLED", "true")
    tenant = SimpleNamespace(id=w.a, status="ACTIVA", is_published=True)
    monkeypatch.setattr(tenancy.SaasRepository, "find_tenant_by_slug", lambda self, slug: tenant)
    token = set_audit_context(None, None)
    try:
        with Session(w.engine) as db:
            app_role(db, w)
            resolved = tenancy.get_public_tenant_id(x_tenant_slug="tienda-a", user=None, credentials=None, db=db)
            assert resolved == w.a
            assert tenant_rows(db, "products") == [w.a]
    finally:
        reset_audit_context(token)


def test_sin_contexto_no_lee_ni_escribe_aunque_flag_este_apagado(pg_pilot):
    w = pg_pilot
    with Session(w.engine) as db:
        app_role(db, w)
        for table in TABLES:
            assert tenant_rows(db, table) == []
        with pytest.raises(DBAPIError):
            db.execute(text("INSERT INTO products VALUES (:id, :tenant)"), dict(id=uuid4(), tenant=w.a))
        db.rollback()


def test_contexto_se_reaplica_en_transaccion_y_no_se_filtra_al_pool(pg_pilot):
    w = pg_pilot
    with Session(w.engine) as db:
        app_role(db, w)
        set_rls_context(db, tenant_id=w.a)
        assert tenant_rows(db, "products") == [w.a]
        db.commit()
        app_role(db, w)
        assert tenant_rows(db, "products") == [w.a]
    with Session(w.engine) as db:
        app_role(db, w)
        assert tenant_rows(db, "products") == []
        set_rls_context(db, tenant_id=w.b)
        assert tenant_rows(db, "products") == [w.b]


def test_migracion_sin_force_y_rol_app_no_dueno(pg_pilot):
    w = pg_pilot
    with w.engine.connect() as c:
        for table in TABLES:
            r = c.execute(text("SELECT relrowsecurity,relforcerowsecurity,pg_get_userbyid(relowner) FROM pg_class WHERE oid=CAST(:name AS regclass)"), {"name": table}).one()
            assert r[0] is True and r[1] is False and r[2] != w.role
