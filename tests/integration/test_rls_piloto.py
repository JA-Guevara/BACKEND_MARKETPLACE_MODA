import os
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text, Column, String, Uuid
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, declarative_base

from src.infrastructure.database.safety import require_local_database
from src.infrastructure.database.session import is_rls_enabled, set_rls_context

PilotBase = declarative_base()


class PilotProduct(PilotBase):
    __tablename__ = "products"
    id = Column(Uuid, primary_key=True)
    tenant_id = Column(Uuid, nullable=False)
    name = Column(String(100), nullable=False)


class PilotOrder(PilotBase):
    __tablename__ = "commerce_orders"
    id = Column(Uuid, primary_key=True)
    tenant_id = Column(Uuid, nullable=False)
    order_number = Column(String(50), nullable=False)


class PilotReservation(PilotBase):
    __tablename__ = "reservations"
    id = Column(Uuid, primary_key=True)
    tenant_id = Column(Uuid, nullable=False)
    code = Column(String(50), nullable=False)


def test_rls_enabled_flag(monkeypatch):
    monkeypatch.setenv("RLS_ENABLED", "true")
    assert is_rls_enabled() is True
    monkeypatch.setenv("RLS_ENABLED", "1")
    assert is_rls_enabled() is True
    monkeypatch.setenv("RLS_ENABLED", "false")
    assert is_rls_enabled() is False
    monkeypatch.delenv("RLS_ENABLED", raising=False)
    assert is_rls_enabled() is False


def test_set_rls_context_sqlite_safe():
    """Verifica que en SQLite no se ejecuten comandos SET LOCAL de PostgreSQL."""
    engine = create_engine("sqlite:///:memory:")
    PilotBase.metadata.create_all(engine)
    with Session(engine) as db:
        # No debe lanzar excepción
        set_rls_context(db, tenant_id=uuid4(), is_platform=False)
        set_rls_context(db, is_platform=True)


@pytest.fixture
def pg_rls_database():
    url_str = os.getenv("TEST_PG_URL") or os.getenv("TEST_DATABASE_URL")
    if not url_str:
        pytest.skip("Requiere TEST_PG_URL o TEST_DATABASE_URL con PostgreSQL real para probar RLS")

    url = make_url(url_str)
    require_local_database(url, allow_remote=False)

    db_name = f"fs_rls_test_{uuid4().hex[:12]}"
    admin_engine = create_engine(url, isolation_level="AUTOCOMMIT")

    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    target_url = url.set(database=db_name)
    test_engine = create_engine(target_url)

    # Crear tablas
    PilotBase.metadata.create_all(test_engine)

    # Aplicar políticas RLS idénticas a la migración 0041
    with test_engine.connect() as conn:
        for tbl in ["products", "commerce_orders", "reservations"]:
            conn.execute(text(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;"))
            conn.execute(text(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;"))
            conn.execute(text(f"""
                CREATE POLICY tenant_isolation_{tbl} ON {tbl}
                AS PERMISSIVE
                FOR ALL
                USING (
                    (NULLIF(current_setting('app.tenant_id', true), '')::uuid IS NOT NULL 
                     AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                    OR current_setting('app.platform', true) = '1'
                )
                WITH CHECK (
                    (NULLIF(current_setting('app.tenant_id', true), '')::uuid IS NOT NULL 
                     AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                    OR current_setting('app.platform', true) = '1'
                );
            """))
            conn.commit()

    yield test_engine

    test_engine.dispose()
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    admin_engine.dispose()


def test_sql_manual_sin_filtro_ve_solo_empresa_del_contexto(pg_rls_database, monkeypatch):
    """Prueba obligatoria PX2.3: Una consulta SQL manual sin filtro solo ve filas de la empresa del contexto en PostgreSQL."""
    monkeypatch.setenv("RLS_ENABLED", "true")
    engine = pg_rls_database

    tenant_a = uuid4()
    tenant_b = uuid4()

    # Insertar filas para tenant_a y tenant_b como plataforma para sembrar datos
    with Session(engine) as db:
        set_rls_context(db, is_platform=True)
        p1 = PilotProduct(id=uuid4(), tenant_id=tenant_a, name="Camisa Lino Azul")
        p2 = PilotProduct(id=uuid4(), tenant_id=tenant_b, name="Vestido Seda Rojo")
        db.add_all([p1, p2])

        o1 = PilotOrder(id=uuid4(), tenant_id=tenant_a, order_number="ORD-001")
        o2 = PilotOrder(id=uuid4(), tenant_id=tenant_b, order_number="ORD-002")
        db.add_all([o1, o2])

        r1 = PilotReservation(id=uuid4(), tenant_id=tenant_a, code="RES-001")
        r2 = PilotReservation(id=uuid4(), tenant_id=tenant_b, code="RES-002")
        db.add_all([r1, r2])
        db.commit()

    # 1. Sesión con contexto de tenant_a: consulta manual sin WHERE debe ver solo tenant_a
    with Session(engine) as db:
        set_rls_context(db, tenant_id=tenant_a)
        res_prod = db.execute(text("SELECT id, tenant_id, name FROM products")).all()
        assert len(res_prod) == 1
        assert res_prod[0].tenant_id == tenant_a
        assert res_prod[0].name == "Camisa Lino Azul"

        res_orders = db.execute(text("SELECT id, tenant_id, order_number FROM commerce_orders")).all()
        assert len(res_orders) == 1
        assert res_orders[0].tenant_id == tenant_a
        assert res_orders[0].order_number == "ORD-001"

        res_res = db.execute(text("SELECT id, tenant_id, code FROM reservations")).all()
        assert len(res_res) == 1
        assert res_res[0].tenant_id == tenant_a
        assert res_res[0].code == "RES-001"

    # 2. Sesión con contexto de tenant_b: consulta manual sin WHERE debe ver solo tenant_b
    with Session(engine) as db:
        set_rls_context(db, tenant_id=tenant_b)
        res_prod = db.execute(text("SELECT id, tenant_id, name FROM products")).all()
        assert len(res_prod) == 1
        assert res_prod[0].tenant_id == tenant_b
        assert res_prod[0].name == "Vestido Seda Rojo"

        res_orders = db.execute(text("SELECT id, tenant_id, order_number FROM commerce_orders")).all()
        assert len(res_orders) == 1
        assert res_orders[0].tenant_id == tenant_b

        res_res = db.execute(text("SELECT id, tenant_id, code FROM reservations")).all()
        assert len(res_res) == 1
        assert res_res[0].tenant_id == tenant_b

    # 3. Sesión con contexto de plataforma (app.platform = '1'): ve todas las filas
    with Session(engine) as db:
        set_rls_context(db, is_platform=True)
        res_prod = db.execute(text("SELECT id, tenant_id, name FROM products")).all()
        assert len(res_prod) == 2
        tenants = {row.tenant_id for row in res_prod}
        assert tenants == {tenant_a, tenant_b}
