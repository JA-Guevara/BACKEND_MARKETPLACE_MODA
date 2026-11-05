"""Gobierno de plataforma, modulos, derechos efectivos y roles de equipo.

Revision ID: 20261104_0029
Revises: 20261105_0021
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import json
from uuid import UUID

from alembic import op
import sqlalchemy as sa


revision: str = "20261104_0029"
down_revision: str | None = "20261105_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_PERMISSIONS = [
    ("20000000-0000-0000-0000-000000000047", "modules.read", "Consultar módulos", "Consultar catálogo de módulos y matriz de planes", "platform", "platform"),
    ("20000000-0000-0000-0000-000000000048", "modules.write", "Gestionar módulos", "Crear y modificar catálogo de módulos y dependencias", "platform", "platform"),
    ("20000000-0000-0000-0000-000000000049", "platform_roles.read", "Consultar roles de plataforma", "Consultar roles de equipo y plantillas del sistema", "platform", "platform"),
    ("20000000-0000-0000-0000-000000000050", "platform_roles.write", "Gestionar roles de plataforma", "Crear y modificar roles de equipo y plantillas", "platform", "platform"),
    ("20000000-0000-0000-0000-000000000051", "tenant_users.write", "Gestionar usuarios de empresas", "Crear, editar y asignar roles a usuarios de empresas desde la consola", "platform", "platform"),
    ("20000000-0000-0000-0000-000000000052", "sandbox.manage", "Gestionar empresa demo", "Acceder, previsualizar y restablecer la empresa demo", "platform", "platform"),
]

ROLE_PLATFORM_ADMIN = UUID("10000000-0000-0000-0000-000000000006")
ROLE_PLATFORM_SUPPORT = UUID("10000000-0000-0000-0000-000000000007")
ROLE_PLATFORM_BILLING = UUID("10000000-0000-0000-0000-000000000008")
ROLE_PLATFORM_AUDITOR = UUID("10000000-0000-0000-0000-000000000009")

INITIAL_MODULES = [
    {
        "code": "products",
        "name": "Catálogo y prendas",
        "description": "Gestión de catálogo, categorías, marcas, atributos, tallas, colores y proveedores.",
        "category": "operaciones",
        "icon": "🏷️",
        "kind": "BASE",
        "lifecycle": "GA",
        "depends_on": [],
        "web_routes": ["/admin/catalogo"],
        "sort_order": 1,
    },
    {
        "code": "inventory",
        "name": "Inventario",
        "description": "Control de stock, existencias por sucursal y movimientos de inventario.",
        "category": "operaciones",
        "icon": "📦",
        "kind": "ADDON",
        "lifecycle": "GA",
        "depends_on": ["products"],
        "web_routes": ["/admin/inventario"],
        "sort_order": 2,
    },
    {
        "code": "sales",
        "name": "Ventas y caja",
        "description": "Punto de venta, cobros, facturación, turnos y arqueos de caja.",
        "category": "operaciones",
        "icon": "💳",
        "kind": "ADDON",
        "lifecycle": "GA",
        "depends_on": ["products"],
        "web_routes": ["/admin/ventas", "/admin/cajas"],
        "sort_order": 3,
    },
    {
        "code": "reservations",
        "name": "Reservas",
        "description": "Reserva de prendas, seña y seguimiento de retiros en sucursal.",
        "category": "operaciones",
        "icon": "📅",
        "kind": "ADDON",
        "lifecycle": "GA",
        "depends_on": ["products"],
        "web_routes": ["/admin/reservas"],
        "sort_order": 4,
    },
    {
        "code": "offline",
        "name": "Operación sin conexión",
        "description": "Venta y consulta de stock en caja local cuando se interrumpe la conexión.",
        "category": "operaciones",
        "icon": "⚡",
        "kind": "ADDON",
        "lifecycle": "GA",
        "depends_on": ["sales"],
        "web_routes": ["/sin-conexion"],
        "sort_order": 5,
    },
    {
        "code": "conventional_reports",
        "name": "Reportes convencionales",
        "description": "Reportes de ventas, stock, recaudación y exportación de datos.",
        "category": "analitica",
        "icon": "📊",
        "kind": "ADDON",
        "lifecycle": "GA",
        "depends_on": [],
        "web_routes": ["/admin/reportes"],
        "sort_order": 6,
    },
    {
        "code": "ai_reports",
        "name": "Reportes con IA",
        "description": "Generación de informes inteligentes y consultas analíticas en lenguaje natural con Gemini.",
        "category": "analitica",
        "icon": "✨",
        "kind": "ADDON",
        "lifecycle": "GA",
        "depends_on": ["conventional_reports"],
        "web_routes": ["/admin/reportes-ia"],
        "sort_order": 7,
    },
    {
        "code": "ml_analytics",
        "name": "Analítica predictiva (ML)",
        "description": "Modelos de pronóstico de demanda, rotación y alertas predictivas.",
        "category": "analitica",
        "icon": "📈",
        "kind": "ADDON",
        "lifecycle": "GA",
        "depends_on": ["sales"],
        "web_routes": ["/admin/analitica"],
        "sort_order": 8,
    },
    {
        "code": "promotions",
        "name": "Ofertas y promociones",
        "description": "Reglas de descuento, cupones, promociones por volumen y temporadas.",
        "category": "marketing",
        "icon": "🏷️",
        "kind": "ADDON",
        "lifecycle": "GA",
        "depends_on": ["products"],
        "web_routes": ["/admin/promociones"],
        "sort_order": 9,
    },
    {
        "code": "virtual_tryon",
        "name": "Probador virtual (RA)",
        "description": "Experiencia interactiva de prueba virtual de prendas con modelos 3D y realidad aumentada.",
        "category": "experiencia",
        "icon": "👗",
        "kind": "ADDON",
        "lifecycle": "GA",
        "depends_on": ["products"],
        "web_routes": ["/admin/probador"],
        "sort_order": 10,
    },
    {
        "code": "exchanges",
        "name": "Cambios de prendas",
        "description": "Gestión de cambios de talla/color, devoluciones y notas de crédito.",
        "category": "operaciones",
        "icon": "🔄",
        "kind": "ADDON",
        "lifecycle": "BETA",
        "depends_on": ["sales"],
        "web_routes": ["/admin/cambios"],
        "sort_order": 11,
    },
    {
        "code": "devices_audit",
        "name": "Dispositivos y auditoría",
        "description": "Registro de terminales POS autorizadas, tokens de dispositivo y bitácora de hardware.",
        "category": "seguridad",
        "icon": "📱",
        "kind": "ADDON",
        "lifecycle": "BETA",
        "depends_on": [],
        "web_routes": ["/admin/dispositivos"],
        "sort_order": 12,
    },
]

MODULE_PERMISSION_MAPPING = {
    "products": ["catalog.read", "catalog.write", "suppliers.read", "suppliers.write"],
    "inventory": ["stock.read", "stock.write"],
    "sales": ["commerce.read", "commerce.write"],
    "reservations": ["reservations.read", "reservations.write"],
}


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    now = datetime.now(timezone.utc)

    # 1. create table platform_modules
    op.create_table(
        "platform_modules",
        sa.Column("code", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(30), nullable=True),
        sa.Column("icon", sa.String(8), nullable=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("lifecycle", sa.String(10), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("web_routes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_preview_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_preview_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('BASE', 'ADDON')", name="ck_platform_modules_kind"),
        sa.CheckConstraint("lifecycle IN ('BORRADOR', 'BETA', 'GA', 'RETIRADO')", name="ck_platform_modules_lifecycle"),
        sa.ForeignKeyConstraint(["last_preview_by"], ["users.id"], ondelete="SET NULL"),
    )

    # 2. create table module_permissions
    op.create_table(
        "module_permissions",
        sa.Column("module_code", sa.String(40), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("module_code", "permission_id"),
        sa.UniqueConstraint("permission_id", name="uq_module_permissions_permission_id"),
        sa.ForeignKeyConstraint(["module_code"], ["platform_modules.code"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
    )

    # 3. create table tenant_modules
    op.create_table(
        "tenant_modules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("module_code", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("revoke_reason", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mode IN ('EXTRA', 'TRIAL', 'BLOQUEADO')", name="ck_tenant_modules_mode"),
        sa.CheckConstraint("mode <> 'TRIAL' OR expires_at IS NOT NULL", name="ck_tenant_modules_trial_expires"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["module_code"], ["platform_modules.code"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "uq_tenant_modules_activo",
        "tenant_modules",
        ["tenant_id", "module_code"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )

    # 4. create table tenant_limits
    op.create_table(
        "tenant_limits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("limit_code", sa.String(40), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("value >= 0", name="ck_tenant_limits_value_positive"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "uq_tenant_limits_activo",
        "tenant_limits",
        ["tenant_id", "limit_code"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )

    # 5. Column tenants.is_sandbox
    op.add_column("tenants", sa.Column("is_sandbox", sa.Boolean(), nullable=False, server_default=sa.text("false" if not is_sqlite else "0")))
    op.create_index(
        "uq_tenants_is_sandbox",
        "tenants",
        ["is_sandbox"],
        unique=True,
        postgresql_where=sa.text("is_sandbox = true"),
        sqlite_where=sa.text("is_sandbox = 1"),
    )

    # 6. Columns on support_sessions
    op.add_column("support_sessions", sa.Column("mode", sa.String(10), nullable=False, server_default="WRITE"))
    op.add_column("support_sessions", sa.Column("landing_module", sa.String(40), nullable=True))
    with op.batch_alter_table("support_sessions") as batch:
        batch.create_check_constraint("ck_support_sessions_mode", "mode IN ('WRITE', 'READ_ONLY')")

    # 7. Column roles.audience
    op.add_column("roles", sa.Column("audience", sa.String(10), nullable=False, server_default="TENANT"))
    with op.batch_alter_table("roles") as batch:
        batch.create_check_constraint("ck_roles_audience", "audience IN ('TENANT', 'PLATFORM')")

    bind.execute(sa.text("UPDATE roles SET audience = 'PLATFORM' WHERE code = 'platform_admin'"))

    # 8. Column users.must_change_password
    inspector = sa.inspect(bind)
    user_columns = [col["name"] for col in inspector.get_columns("users")]
    if "must_change_password" not in user_columns:
        op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false" if not is_sqlite else "0")))

    # 9. Seed platform_modules
    for mod in INITIAL_MODULES:
        bind.execute(
            sa.text("""
                INSERT INTO platform_modules (code, name, description, category, icon, kind, lifecycle, depends_on, web_routes, sort_order, created_at, updated_at)
                VALUES (:code, :name, :description, :category, :icon, :kind, :lifecycle, :depends_on, :web_routes, :sort_order, :created_at, :updated_at)
            """),
            {
                "code": mod["code"],
                "name": mod["name"],
                "description": mod["description"],
                "category": mod["category"],
                "icon": mod["icon"],
                "kind": mod["kind"],
                "lifecycle": mod["lifecycle"],
                "depends_on": json.dumps(mod["depends_on"]),
                "web_routes": json.dumps(mod["web_routes"]),
                "sort_order": mod["sort_order"],
                "created_at": now,
                "updated_at": now,
            },
        )

    # 10. Seed module_permissions
    for mod_code, perm_codes in MODULE_PERMISSION_MAPPING.items():
        for pcode in perm_codes:
            bind.execute(
                sa.text("""
                    INSERT INTO module_permissions (module_code, permission_id)
                    SELECT :module_code, id FROM permissions WHERE code = :pcode
                """),
                {"module_code": mod_code, "pcode": pcode},
            )

    # 11. Insert permissions 47..52
    for pid_str, pcode, pname, pdesc, pmodule, pscope in NEW_PERMISSIONS:
        pid = UUID(pid_str)
        bind.execute(
            sa.text("""
                INSERT INTO permissions (id, code, name, description, module, scope, is_active, created_at, updated_at)
                VALUES (:id, :code, :name, :description, :module, :scope, :is_active, :created_at, :updated_at)
            """),
            {
                "id": pid.hex if is_sqlite else pid,
                "code": pcode,
                "name": pname,
                "description": pdesc,
                "module": pmodule,
                "scope": pscope,
                "is_active": True if not is_sqlite else 1,
                "created_at": now,
                "updated_at": now,
            },
        )
        # Assign to platform_admin
        bind.execute(
            sa.text("""
                INSERT INTO role_permissions (role_id, permission_id)
                VALUES (:role_id, :permission_id)
            """),
            {
                "role_id": ROLE_PLATFORM_ADMIN.hex if is_sqlite else ROLE_PLATFORM_ADMIN,
                "permission_id": pid.hex if is_sqlite else pid,
            },
        )

    # 12. Create PLATFORM roles: platform_support, platform_billing, platform_auditor
    platform_roles_data = [
        (
            ROLE_PLATFORM_SUPPORT,
            "platform_support",
            "Soporte de plataforma",
            "Equipo de soporte técnico y asistencia a clientes",
            [
                "tenants.read",
                "platform_users.read",
                "tenant_users.write",
                "support.access",
                "support_sessions.read",
                "platform_audit.read",
                "modules.read",
            ],
        ),
        (
            ROLE_PLATFORM_BILLING,
            "platform_billing",
            "Comercial y facturación",
            "Gestión comercial de planes, suscripciones y módulos",
            [
                "tenants.read",
                "plans.read",
                "plans.write",
                "subscriptions.read",
                "subscriptions.write",
                "modules.read",
            ],
        ),
        (
            ROLE_PLATFORM_AUDITOR,
            "platform_auditor",
            "Auditor de plataforma",
            "Auditoría global, trazabilidad y supervisión de accesos",
            [
                "tenants.read",
                "plans.read",
                "subscriptions.read",
                "platform_users.read",
                "platform_audit.read",
                "modules.read",
                "platform_roles.read",
            ],
        ),
    ]

    for rid, rcode, rname, rdesc, rperms in platform_roles_data:
        bind.execute(
            sa.text("""
                INSERT INTO roles (id, tenant_id, code, name, description, audience, is_system, is_active, created_at, updated_at)
                VALUES (:id, NULL, :code, :name, :description, 'PLATFORM', :is_system, :is_active, :created_at, :updated_at)
            """),
            {
                "id": rid.hex if is_sqlite else rid,
                "code": rcode,
                "name": rname,
                "description": rdesc,
                "is_system": True if not is_sqlite else 1,
                "is_active": True if not is_sqlite else 1,
                "created_at": now,
                "updated_at": now,
            },
        )
        for pcode in rperms:
            bind.execute(
                sa.text("""
                    INSERT INTO role_permissions (role_id, permission_id)
                    SELECT :role_id, id FROM permissions WHERE code = :pcode
                """),
                {
                    "role_id": rid.hex if is_sqlite else rid,
                    "pcode": pcode,
                },
            )

    # 13. Update plan_features
    # inventory, promotions, virtual_tryon, exchanges, devices_audit, ml_analytics
    features_to_insert = [
        ("inventory", True, True),
        ("promotions", True, True),
        ("virtual_tryon", False, True),  # Basico: False, Profesional: True
        ("ml_analytics", True, True),   # Basico: True (decision 04/11), Profesional: True
        ("exchanges", False, False),    # BETA
        ("devices_audit", False, False),# BETA
    ]

    # Find existing plans
    plans_res = bind.execute(sa.text("SELECT id, code FROM plans")).fetchall()
    for plan_row in plans_res:
        plan_id = plan_row[0]
        plan_code = (plan_row[1] or "").upper()
        is_profesional = "PRO" in plan_code

        for feat_name, in_basico, in_profesional in features_to_insert:
            enabled = in_profesional if is_profesional else in_basico
            # Check if feature already exists for plan
            exists = bind.execute(
                sa.text("SELECT 1 FROM plan_features WHERE plan_id = :plan_id AND feature_code = :feature"),
                {"plan_id": plan_id, "feature": feat_name},
            ).scalar()

            if not exists:
                import uuid as _uuid_module
                bind.execute(
                    sa.text("""
                        INSERT INTO plan_features (id, plan_id, feature_code, enabled)
                        VALUES (:id, :plan_id, :feature, :enabled)
                    """),
                    {
                        "id": _uuid_module.uuid4().hex if is_sqlite else _uuid_module.uuid4(),
                        "plan_id": plan_id,
                        "feature": feat_name,
                        "enabled": enabled if not is_sqlite else (1 if enabled else 0),
                    },
                )
            else:
                bind.execute(
                    sa.text("""
                        UPDATE plan_features SET enabled = :enabled
                        WHERE plan_id = :plan_id AND feature_code = :feature
                    """),
                    {
                        "plan_id": plan_id,
                        "feature": feat_name,
                        "enabled": enabled if not is_sqlite else (1 if enabled else 0),
                    },
                )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # 1. Delete platform roles
    for rid in [ROLE_PLATFORM_SUPPORT, ROLE_PLATFORM_BILLING, ROLE_PLATFORM_AUDITOR]:
        bind.execute(
            sa.text("DELETE FROM role_permissions WHERE role_id = :role_id"),
            {"role_id": rid.hex if is_sqlite else rid},
        )
        bind.execute(
            sa.text("DELETE FROM roles WHERE id = :role_id"),
            {"role_id": rid.hex if is_sqlite else rid},
        )

    # 2. Delete permissions 47..52
    for pid_str, pcode, _, _, _, _ in NEW_PERMISSIONS:
        pid = UUID(pid_str)
        bind.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_id = :permission_id"),
            {"permission_id": pid.hex if is_sqlite else pid},
        )
        bind.execute(
            sa.text("DELETE FROM permissions WHERE id = :permission_id"),
            {"permission_id": pid.hex if is_sqlite else pid},
        )

    # 3. Delete added plan_features
    for feat in ["inventory", "promotions", "virtual_tryon", "exchanges", "devices_audit"]:
        bind.execute(sa.text("DELETE FROM plan_features WHERE feature_code = :feature"), {"feature": feat})

    # 4. Drop columns
    inspector = sa.inspect(bind)
    user_columns = [col["name"] for col in inspector.get_columns("users")]
    if "must_change_password" in user_columns:
        with op.batch_alter_table("users") as batch:
            batch.drop_column("must_change_password")

    with op.batch_alter_table("roles") as batch:
        for constraint in sa.inspect(bind).get_check_constraints("roles"):
            if constraint["name"] and "audience" in constraint["sqltext"]:
                batch.drop_constraint(op.f(constraint["name"]), type_="check")
        batch.drop_column("audience")

    with op.batch_alter_table("support_sessions") as batch:
        for constraint in sa.inspect(bind).get_check_constraints("support_sessions"):
            if constraint["name"] and "mode" in constraint["sqltext"]:
                batch.drop_constraint(op.f(constraint["name"]), type_="check")
        batch.drop_column("landing_module")
        batch.drop_column("mode")

    op.drop_index("uq_tenants_is_sandbox", table_name="tenants")
    with op.batch_alter_table("tenants") as batch:
        batch.drop_column("is_sandbox")

    # 5. Drop tables
    op.drop_index("uq_tenant_limits_activo", table_name="tenant_limits")
    op.drop_table("tenant_limits")

    op.drop_index("uq_tenant_modules_activo", table_name="tenant_modules")
    op.drop_table("tenant_modules")

    op.drop_table("module_permissions")
    op.drop_table("platform_modules")
