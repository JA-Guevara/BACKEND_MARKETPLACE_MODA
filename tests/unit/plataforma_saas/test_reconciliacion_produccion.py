"""0031 repara un esquema mixto como el de produccion y es idempotente.

La prueba usa SQLite con las tablas minimas que toca la migracion. No pretende
reemplazar el ensayo contra PostgreSQL: valida la logica de reparacion, los
datos sembrados y el ciclo upgrade -> downgrade -> upgrade.
"""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def _cargar_migracion():
    spec = importlib.util.spec_from_file_location(
        "reconciliacion_produccion_qa",
        Path(__file__).resolve().parents[3] / "alembic/versions/20261109_0031_reconciliar_esquema_produccion.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _crear_esquema_mixto(engine):
    metadata = sa.MetaData()
    now = datetime.now(timezone.utc)

    tenants = sa.Table(
        "tenants",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("legal_name", sa.String(200), nullable=False),
        sa.Column("trade_name", sa.String(150), nullable=False),
        sa.Column("tax_id", sa.String(30), nullable=False),
        sa.Column("slug", sa.String(60), nullable=False),
        sa.Column("contact_email", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("is_sandbox", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    ml_models = sa.Table(
        "ml_models",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("model_type", sa.String(50), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    permissions = sa.Table(
        "permissions",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("module", sa.String(40), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    roles = sa.Table(
        "roles",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("audience", sa.String(10), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    role_permissions = sa.Table(
        "role_permissions",
        metadata,
        sa.Column("role_id", sa.Uuid(), primary_key=True),
        sa.Column("permission_id", sa.Uuid(), primary_key=True),
    )
    platform_modules = sa.Table(
        "platform_modules",
        metadata,
        sa.Column("code", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
    )
    module_permissions = sa.Table(
        "module_permissions",
        metadata,
        sa.Column("module_code", sa.String(40), primary_key=True),
        sa.Column("permission_id", sa.Uuid(), primary_key=True),
    )
    catalog_copies = sa.Table(
        "_rs_catalog_copies",
        metadata,
        sa.Column("table_name", sa.String(50), nullable=False),
        sa.Column("copy_id", sa.Uuid(), primary_key=True),
        sa.Column("original_id", sa.Uuid(), nullable=False),
    )

    metadata.create_all(engine)

    tenant_id = uuid4()
    admin_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            tenants.insert().values(
                id=tenant_id,
                legal_name="FashionStore",
                trade_name="FashionStore",
                tax_id="0000000001",
                slug="fashionstore",
                contact_email="contacto@fashionstore.test",
                status="ACTIVA",
                is_sandbox=False,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            users.insert().values(
                id=uuid4(),
                email="admin@fashionstore.test",
                password_hash="hash",
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            roles.insert(),
            [
                {
                    "id": admin_id,
                    "code": "admin",
                    "name": "Administrador",
                    "description": None,
                    "audience": "TENANT",
                    "is_system": True,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": uuid4(),
                    "code": "superadmin",
                    "name": "Superadministrador",
                    "description": None,
                    "audience": "TENANT",
                    "is_system": True,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": uuid4(),
                    "code": "store_manager",
                    "name": "Encargado",
                    "description": None,
                    "audience": "TENANT",
                    "is_system": True,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": uuid4(),
                    "code": "platform_admin",
                    "name": "Plataforma",
                    "description": None,
                    "audience": "PLATFORM",
                    "is_system": True,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
        connection.execute(
            platform_modules.insert().values(code="ai_reports", name="Reportes con IA")
        )
        connection.execute(
            module_permissions.insert().values(module_code="ai_reports", permission_id=uuid4())
        )


def test_0031_repara_esquema_mixto_y_es_idempotente():
    migration = _cargar_migracion()
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        _crear_esquema_mixto(engine)

        def run(direction):
            with engine.begin() as connection:
                with Operations.context(MigrationContext.configure(connection)):
                    getattr(migration, direction)()

        run("upgrade")

        with engine.connect() as connection:
            inspector = sa.inspect(connection)
            tables = set(inspector.get_table_names())

            assert {
                "catalog_template_imports",
                "catalog_templates",
                "report_requests",
                "tenant_payment_methods",
                "upgrade_requests",
                "usage_alerts",
            } <= tables
            assert "_rs_catalog_copies" not in tables

            tenant_columns = {c["name"] for c in inspector.get_columns("tenants")}
            assert {
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
            } <= tenant_columns

            ml_columns = {c["name"] for c in inspector.get_columns("ml_models")}
            assert {"artifact", "artifact_bytes", "artifact_sha256"} <= ml_columns
            assert "file_path" not in ml_columns

            report_indexes = {i["name"] for i in inspector.get_indexes("report_requests")}
            assert "ix_report_requests_user_id" in report_indexes

            module_unique = {
                c["name"] for c in inspector.get_unique_constraints("module_permissions")
            }
            assert "uq_module_permissions_permission_id" in module_unique

            permission_codes = {
                row[0]
                for row in connection.execute(
                    sa.text(
                        "SELECT code FROM permissions WHERE code IN "
                        "('ai_reports.use','ai_reports.history','storefront.write',"
                        "'payment_methods.write','catalog_templates.write','upgrade_requests.manage')"
                    )
                ).fetchall()
            }
            assert permission_codes == {
                "ai_reports.use",
                "ai_reports.history",
                "storefront.write",
                "payment_methods.write",
                "catalog_templates.write",
                "upgrade_requests.manage",
            }

            assert connection.scalar(sa.text("SELECT count(*) FROM catalog_templates")) == 4
            assert connection.scalar(
                sa.text("SELECT count(*) FROM role_permissions WHERE role_id = :role_id"),
                {"role_id": connection.scalar(sa.text("SELECT id FROM roles WHERE code='admin'"))},
            ) == 4

        run("downgrade")
        with engine.connect() as connection:
            inspector = sa.inspect(connection)
            assert "_rs_catalog_copies" in inspector.get_table_names()
            report_indexes = {i["name"] for i in inspector.get_indexes("report_requests")}
            assert "ix_report_requests_user_id" not in report_indexes

        run("upgrade")
        with engine.connect() as connection:
            assert "_rs_catalog_copies" not in sa.inspect(connection).get_table_names()
            assert connection.scalar(sa.text("SELECT count(*) FROM catalog_templates")) == 4
    finally:
        engine.dispose()


def test_0031_revoca_permisos_globales_de_roles_empresa_y_conserva_plataforma():
    migration = _cargar_migracion()
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        _crear_esquema_mixto(engine)
        with engine.begin() as connection:
            # Reproducir asignaciones anteriores, incluso en un rol personalizado.
            connection.execute(sa.text(
                "INSERT INTO roles (id, tenant_id, code, name, audience, is_system, is_active, created_at, updated_at) "
                "SELECT :id, id, 'custom', 'Personalizado', 'PLATFORM', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
                "FROM tenants LIMIT 1"
            ), {"id": uuid4().hex})
            for code in ("catalog_templates.write", "upgrade_requests.manage", "ml_models.manage"):
                connection.execute(sa.text(
                    "INSERT INTO permissions (id, code, name, module, scope, is_active, created_at, updated_at) "
                    "VALUES (:id, :code, :code, 'platform', 'platform', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ), {"id": uuid4().hex, "code": code})
            connection.execute(sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r, permissions p "
                "WHERE p.scope = 'platform'"
            ))

        for _ in range(2):
            with engine.begin() as connection:
                with Operations.context(MigrationContext.configure(connection)):
                    migration.upgrade()
            with engine.connect() as connection:
                assert connection.scalar(sa.text(
                    "SELECT count(*) FROM role_permissions rp JOIN roles r ON r.id=rp.role_id "
                    "JOIN permissions p ON p.id=rp.permission_id WHERE p.scope='platform' "
                    "AND (r.audience <> 'PLATFORM' OR r.tenant_id IS NOT NULL)"
                )) == 0
                assert connection.scalar(sa.text(
                    "SELECT count(*) FROM role_permissions rp JOIN roles r ON r.id=rp.role_id "
                    "JOIN permissions p ON p.id=rp.permission_id "
                    "WHERE r.code='platform_admin' AND p.scope='platform'"
                )) == 3
    finally:
        engine.dispose()
