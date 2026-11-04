"""Pruebas de las migraciones 0019, 0020 y 0021 de Reestructuracion SaaS."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sqlite3
from uuid import UUID, uuid4
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

VERSIONS_DIR = Path(__file__).resolve().parents[3] / "alembic/versions"


def load_migration(name: str):
    path = next(VERSIONS_DIR.glob(f"*{name}*.py"))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mig_0019 = load_migration("0019")
mig_0020 = load_migration("0020")
mig_0021 = load_migration("0021")


def run_op(conn, migration_module, direction: str):
    with Operations.context(MigrationContext.configure(conn)):
        getattr(migration_module, direction)()


def create_pre_0019_database():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(sa.text("""
            CREATE TABLE tenants (
                id TEXT PRIMARY KEY,
                legal_name TEXT,
                trade_name TEXT,
                tax_id TEXT,
                slug TEXT,
                contact_email TEXT,
                status TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                email TEXT,
                first_name TEXT,
                last_name TEXT,
                password_hash TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE branches (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                code TEXT,
                name TEXT,
                city_id TEXT,
                address TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE categories (
                id TEXT PRIMARY KEY,
                name TEXT,
                slug TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                CONSTRAINT uq_categories_slug UNIQUE (slug)
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE sizes (
                id TEXT PRIMARY KEY,
                code TEXT,
                name TEXT,
                category_id TEXT,
                sort_order INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                CONSTRAINT uq_sizes_code UNIQUE (code)
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE colors (
                id TEXT PRIMARY KEY,
                name TEXT,
                hex_code TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                CONSTRAINT uq_colors_name UNIQUE (name),
                CONSTRAINT uq_colors_hex_code UNIQUE (hex_code)
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE seasons (
                id TEXT PRIMARY KEY,
                name TEXT,
                code TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                CONSTRAINT uq_seasons_name UNIQUE (name)
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE collections (
                id TEXT PRIMARY KEY,
                name TEXT,
                code TEXT,
                season_id TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                CONSTRAINT uq_collections_name UNIQUE (name, season_id)
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE suppliers (
                id TEXT PRIMARY KEY,
                name TEXT,
                contact_name TEXT,
                email TEXT,
                phone TEXT,
                tax_id TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                CONSTRAINT uq_suppliers_tax_id UNIQUE (tax_id)
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE products (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                name TEXT,
                slug TEXT,
                description TEXT,
                base_price REAL,
                category_id TEXT,
                season_id TEXT,
                collection_id TEXT,
                is_active INTEGER DEFAULT 1,
                is_featured INTEGER DEFAULT 0,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE product_variants (
                id TEXT PRIMARY KEY,
                product_id TEXT,
                size_id TEXT,
                color_id TEXT,
                sku TEXT,
                barcode TEXT,
                price_override REAL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE product_suppliers (
                product_id TEXT,
                supplier_id TEXT,
                supplier_sku TEXT,
                cost_price REAL,
                is_primary INTEGER DEFAULT 0,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                PRIMARY KEY (product_id, supplier_id)
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE commerce_orders (
                id TEXT PRIMARY KEY,
                number TEXT,
                customer_email TEXT,
                branch_id TEXT,
                status TEXT,
                payment_status TEXT,
                payment_method TEXT,
                total REAL,
                subtotal REAL,
                discount_total REAL,
                discounts TEXT,
                currency TEXT,
                address TEXT,
                items TEXT,
                tracking TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE commerce_order_returns (
                id TEXT PRIMARY KEY,
                order_id TEXT,
                branch_id TEXT,
                number TEXT,
                reason TEXT,
                status TEXT,
                items TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE commerce_promotions (
                id TEXT PRIMARY KEY,
                code TEXT,
                name TEXT,
                type TEXT,
                value REAL,
                min_purchase REAL,
                category_id TEXT,
                product_id TEXT,
                starts_at TIMESTAMP,
                ends_at TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                CONSTRAINT uq_commerce_promotions_code UNIQUE (code)
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE virtual_tryon_assets (
                id TEXT PRIMARY KEY,
                product_id TEXT,
                color_id TEXT,
                name TEXT,
                user_id TEXT,
                type TEXT,
                status TEXT,
                url TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE tryon_ai_jobs (
                id TEXT PRIMARY KEY,
                product_id TEXT,
                user_id TEXT,
                status TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE permissions (
                id TEXT PRIMARY KEY,
                code TEXT UNIQUE,
                name TEXT,
                module TEXT,
                description TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE roles (
                id TEXT PRIMARY KEY,
                code TEXT,
                name TEXT,
                description TEXT,
                is_system INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                is_default INTEGER DEFAULT 0,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                CONSTRAINT uq_roles_code UNIQUE (code)
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE role_permissions (
                role_id TEXT,
                permission_id TEXT,
                PRIMARY KEY (role_id, permission_id)
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE audit_events (
                id TEXT PRIMARY KEY,
                actor_user_id TEXT,
                action TEXT,
                entity_type TEXT,
                entity_id TEXT,
                description TEXT,
                metadata TEXT,
                ip_address TEXT,
                user_agent TEXT,
                created_at TIMESTAMP
            );
        """))
    return engine


def test_migraciones_rs_ciclo_completo():
    engine = create_pre_0019_database()
    now = datetime.now(timezone.utc)
    tenant_1_id = mig_0019.INITIAL_TENANT
    tenant_2_id = uuid4()
    branch_1_id = uuid4()
    cat_vestidos_id = uuid4()
    cat_huerfana_id = uuid4()
    prod_1_id = uuid4()
    prod_2_id = uuid4()
    order_id = uuid4()
    role_admin_id = uuid4()
    role_plat_id = uuid4()
    perm_tenants_read_id = uuid4()
    perm_catalog_read_id = uuid4()

    with engine.begin() as conn:
        # Tenants
        conn.execute(
            sa.text("""
                INSERT INTO tenants (id, legal_name, trade_name, tax_id, slug, contact_email, status, created_at, updated_at)
                VALUES (:id, 'Empresa Uno', 'Uno', '1111111111', 'empresa-uno', 'uno@test.com', 'ACTIVA', :now, :now)
            """),
            {"id": str(tenant_1_id), "now": now},
        )
        conn.execute(
            sa.text("""
                INSERT INTO tenants (id, legal_name, trade_name, tax_id, slug, contact_email, status, created_at, updated_at)
                VALUES (:id, 'Empresa Dos', 'Dos', '9999999999', 'empresa-dos', 'dos@test.com', 'ACTIVA', :now, :now)
            """),
            {"id": str(tenant_2_id), "now": now},
        )

        # Sucursal de Empresa 1
        conn.execute(
            sa.text("""
                INSERT INTO branches (id, tenant_id, code, name, city_id, address, is_active, created_at, updated_at)
                VALUES (:id, :tid, 'CENTRAL', 'Central', 'scz', 'Av 1', 1, :now, :now)
            """),
            {"id": str(branch_1_id), "tid": str(tenant_1_id), "now": now},
        )

        # Categorias compartidas (pre-0019 no tenian tenant_id)
        conn.execute(
            sa.text("""
                INSERT INTO categories (id, name, slug, is_active, created_at, updated_at)
                VALUES (:id, 'Vestidos', 'vestidos', 1, :now, :now)
            """),
            {"id": str(cat_vestidos_id), "now": now},
        )
        conn.execute(
            sa.text("""
                INSERT INTO categories (id, name, slug, is_active, created_at, updated_at)
                VALUES (:id, 'Accesorios', 'accesorios', 1, :now, :now)
            """),
            {"id": str(cat_huerfana_id), "now": now},
        )

        # Prenda Empresa 1
        conn.execute(
            sa.text("""
                INSERT INTO products (id, tenant_id, name, slug, description, base_price, category_id, is_active, is_featured, created_at, updated_at)
                VALUES (:id, :tid, 'Vestido Rojo T1', 'vestido-rojo-t1', 'Desc', 100, :cat_id, 1, 0, :now, :now)
            """),
            {"id": str(prod_1_id), "tid": str(tenant_1_id), "cat_id": str(cat_vestidos_id), "now": now},
        )

        # Prenda Empresa 2 con la misma categoria Vestidos
        conn.execute(
            sa.text("""
                INSERT INTO products (id, tenant_id, name, slug, description, base_price, category_id, is_active, is_featured, created_at, updated_at)
                VALUES (:id, :tid, 'Vestido Azul T2', 'vestido-azul-t2', 'Desc', 120, :cat_id, 1, 0, :now, :now)
            """),
            {"id": str(prod_2_id), "tid": str(tenant_2_id), "cat_id": str(cat_vestidos_id), "now": now},
        )

        # Pedido sin tenant_id en sucursal de Empresa 1
        conn.execute(
            sa.text("""
                INSERT INTO commerce_orders (id, number, customer_email, branch_id, status, payment_status, payment_method, total, subtotal, discount_total, discounts, currency, address, items, tracking, created_at, updated_at)
                VALUES (:id, 'FS-ORD-MIG', 'cli@test.com', :bid, 'pending_payment', 'pending', 'manual', 100, 100, 0, '[]', 'BOB', '{}', '[]', '[]', :now, :now)
            """),
            {"id": str(order_id), "bid": str(branch_1_id), "now": now},
        )

        # Roles y permisos existentes
        conn.execute(
            sa.text("""
                INSERT INTO permissions (id, code, name, module, description, created_at)
                VALUES (:id1, 'tenants.read', 'Leer empresas', 'tenants', 'Desc', :now),
                           (:id2, 'catalog.read', 'Leer catalogo', 'catalog', 'Desc', :now)
            """),
            {"id1": str(perm_tenants_read_id), "id2": str(perm_catalog_read_id), "now": now},
        )
        conn.execute(
            sa.text("""
                INSERT INTO roles (id, code, name, is_system, is_default, created_at, updated_at)
                VALUES (:id1, 'admin', 'Administrador', 1, 0, :now, :now),
                           (:id2, 'platform_admin', 'Plataforma', 1, 0, :now, :now)
            """),
            {"id1": str(role_admin_id), "id2": str(role_plat_id), "now": now},
        )
        conn.execute(
            sa.text("""
                INSERT INTO role_permissions (role_id, permission_id)
                VALUES (:rid1, :pid2), (:rid2, :pid1)
            """),
            {"rid1": str(role_admin_id), "pid2": str(perm_catalog_read_id),
             "rid2": str(role_plat_id), "pid1": str(perm_tenants_read_id)},
        )

    # 1. Ejecutar Upgrade 0019, 0020, 0021
    with engine.begin() as conn:
        run_op(conn, mig_0019, "upgrade")
        run_op(conn, mig_0020, "upgrade")
        run_op(conn, mig_0021, "upgrade")

    with engine.begin() as conn:
        # Caso 1: Dos empresas que compartian 'Vestidos' -> ahora 2 filas 'Vestidos', una por empresa
        vestidos_rows = conn.execute(
            sa.text("SELECT id, tenant_id FROM categories WHERE name = 'Vestidos'")
        ).fetchall()
        assert len(vestidos_rows) == 2
        vestidos_tenants = {UUID(str(r[1])) for r in vestidos_rows}
        assert vestidos_tenants == {tenant_1_id, tenant_2_id}

        # Cada prenda apunta a la categoria de su empresa
        p1_cat_tid = conn.scalar(
            sa.text("SELECT c.tenant_id FROM products p JOIN categories c ON p.category_id = c.id WHERE p.id = :pid"),
            {"pid": str(prod_1_id)},
        )
        assert UUID(str(p1_cat_tid)) == tenant_1_id

        p2_cat_tid = conn.scalar(
            sa.text("SELECT c.tenant_id FROM products p JOIN categories c ON p.category_id = c.id WHERE p.id = :pid"),
            {"pid": str(prod_2_id)},
        )
        assert UUID(str(p2_cat_tid)) == tenant_2_id

        # Caso 2: Categoria sin prendas -> queda en la empresa inicial
        cat_huerfana_tid = conn.scalar(
            sa.text("SELECT tenant_id FROM categories WHERE id = :id"),
            {"id": str(cat_huerfana_id)},
        )
        assert UUID(str(cat_huerfana_tid)) == tenant_1_id

        # Caso 3: commerce_orders sin tenant_id tras upgrade -> 0 filas
        orders_sin_tenant = conn.scalar(
            sa.text("SELECT COUNT(*) FROM commerce_orders WHERE tenant_id IS NULL")
        )
        assert orders_sin_tenant == 0

        order_tid = conn.scalar(
            sa.text("SELECT tenant_id FROM commerce_orders WHERE id = :id"),
            {"id": str(order_id)},
        )
        assert UUID(str(order_tid)) == tenant_1_id

        # Caso 4: permissions con code tenants.read -> scope "platform"; catalog.read -> "tenant"
        scope_tenants_read = conn.scalar(
            sa.text("SELECT scope FROM permissions WHERE code = 'tenants.read'")
        )
        assert scope_tenants_read == "platform"

        scope_catalog_read = conn.scalar(
            sa.text("SELECT scope FROM permissions WHERE code = 'catalog.read'")
        )
        assert scope_catalog_read == "tenant"

        # Caso 5: Rol admin recibe tenant_profile.write y support_sessions.read; platform_admin recibe support.access
        admin_perms = set(conn.scalars(
            sa.text("""
                SELECT p.code FROM role_permissions rp
                JOIN permissions p ON rp.permission_id = p.id
                JOIN roles r ON rp.role_id = r.id
                WHERE r.code = 'admin'
            """)
        ).all())
        assert "tenant_profile.write" in admin_perms
        assert "support_sessions.read" in admin_perms

        platform_perms = set(conn.scalars(
            sa.text("""
                SELECT p.code FROM role_permissions rp
                JOIN permissions p ON rp.permission_id = p.id
                JOIN roles r ON rp.role_id = r.id
                WHERE r.code = 'platform_admin'
            """)
        ).all())
        assert "support.access" in platform_perms

    # Caso 6: Downgrade a 0018 y upgrade de nuevo sin errores
    with engine.begin() as conn:
        run_op(conn, mig_0021, "downgrade")
        run_op(conn, mig_0020, "downgrade")
        run_op(conn, mig_0019, "downgrade")

    with engine.begin() as conn:
        # Despues del downgrade, 'Vestidos' vuelve a 1 sola fila original
        vestidos_downgrade = conn.execute(
            sa.text("SELECT id FROM categories WHERE name = 'Vestidos'")
        ).fetchall()
        assert len(vestidos_downgrade) == 1

    # Upgrade de nuevo para verificar idempotencia y reejecucion limpia
    with engine.begin() as conn:
        run_op(conn, mig_0019, "upgrade")
        run_op(conn, mig_0020, "upgrade")
        run_op(conn, mig_0021, "upgrade")

    with engine.begin() as conn:
        vestidos_reupgrade = conn.execute(
            sa.text("SELECT id FROM categories WHERE name = 'Vestidos'")
        ).fetchall()
        assert len(vestidos_reupgrade) == 2
