"""Roles por empresa, alcance de permisos, bitacora con empresa y sesiones de soporte.

Revision ID: 20261105_0021
Revises: 20261105_0020
"""
from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from alembic import op
import sqlalchemy as sa


revision: str = "20261105_0021"
down_revision: str | None = "20261105_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = [
    ("20000000-0000-0000-0000-000000000026", "support.access", "Acceso de soporte", "Acceso de soporte a empresas", "platform", "platform"),
    ("20000000-0000-0000-0000-000000000027", "platform_users.read", "Consultar usuarios globales", "Consultar usuarios globales de la plataforma", "platform", "platform"),
    ("20000000-0000-0000-0000-000000000028", "platform_users.write", "Gestionar usuarios de plataforma", "Gestionar usuarios y administradores de plataforma", "platform", "platform"),
    ("20000000-0000-0000-0000-000000000029", "platform_audit.read", "Consultar auditoría global", "Consultar bitácora y sesiones de soporte globales", "platform", "platform"),
    ("20000000-0000-0000-0000-000000000030", "tenant_profile.write", "Editar perfil de empresa", "Actualizar datos y perfil de la empresa", "tenant", "tenant"),
    ("20000000-0000-0000-0000-000000000031", "support_sessions.read", "Consultar accesos de soporte", "Consultar historial de accesos de soporte", "tenant", "tenant"),
    ("20000000-0000-0000-0000-000000000032", "cities.write", "Gestionar ciudades", "Crear y modificar catálogo global de ciudades", "platform", "platform"),
]

PLATFORM_PERM_CODES = {
    "tenants.read", "tenants.write",
    "plans.read", "plans.write",
    "subscriptions.read", "subscriptions.write",
    "support.access", "platform_users.read", "platform_users.write",
    "platform_audit.read", "cities.write",
}

ROLE_PLATFORM_ADMIN = UUID("10000000-0000-0000-0000-000000000006")
ROLE_SUPERADMIN = UUID("10000000-0000-0000-0000-000000000001")
ROLE_ADMIN = UUID("10000000-0000-0000-0000-000000000002")


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    # 1. support_sessions (crear antes de que audit_events cree FK hacia ella)
    op.create_table(
        "support_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("platform_user_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(20), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_support_sessions_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["platform_user_id"], ["users.id"], name="fk_support_sessions_platform_user_id_users", ondelete="RESTRICT"),
        sa.CheckConstraint("end_reason IS NULL OR end_reason IN ('manual', 'expired', 'revoked')", name="ck_support_sessions_end_reason"),
    )
    op.create_index("ix_support_sessions_tenant_id", "support_sessions", ["tenant_id"])
    op.create_index("ix_support_sessions_platform_user_id", "support_sessions", ["platform_user_id"])

    # 2. roles: tenant_id nullable FK, uniques
    op.add_column("roles", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    with op.batch_alter_table("roles") as batch:
        batch.create_foreign_key("fk_roles_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_roles_tenant_id", ["tenant_id"])
        try:
            batch.drop_constraint("uq_roles_code", type_="unique")
        except Exception:
            pass
        batch.create_unique_constraint("uq_roles_tenant_code", ["tenant_id", "code"])

    op.create_index(
        "uq_roles_system_code",
        "roles",
        ["code"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
        sqlite_where=sa.text("tenant_id IS NULL"),
    )

    # 3. permissions: scope column y check
    op.add_column("permissions", sa.Column("scope", sa.String(10), nullable=False, server_default="tenant"))
    with op.batch_alter_table("permissions") as batch:
        batch.create_check_constraint("ck_permissions_scope", "scope IN ('tenant', 'platform')")

    # Backfill scope de permisos de plataforma existentes
    bind.execute(sa.text("""
        UPDATE permissions
        SET scope = 'platform'
        WHERE code IN ('tenants.read', 'tenants.write', 'plans.read', 'plans.write', 'subscriptions.read', 'subscriptions.write')
    """))

    # 4. audit_events: tenant_id y support_session_id
    op.add_column("audit_events", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.add_column("audit_events", sa.Column("support_session_id", sa.Uuid(), nullable=True))

    bind.execute(sa.text("""
        UPDATE audit_events
        SET tenant_id = (SELECT u.tenant_id FROM users u WHERE u.id = audit_events.actor_user_id)
        WHERE tenant_id IS NULL AND actor_user_id IS NOT NULL
    """))

    with op.batch_alter_table("audit_events") as batch:
        batch.create_foreign_key("fk_audit_events_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_audit_events_support_session_id_support_sessions", "support_sessions", ["support_session_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_audit_events_tenant_id", ["tenant_id"])
        batch.create_index("ix_audit_events_support_session_id", ["support_session_id"])

    # 5. Insertar permisos 26 a 32
    for pid_str, code, name, desc, module, scope in NEW_PERMISSIONS:
        pid = UUID(pid_str)
        bind.execute(
            sa.text("""
                INSERT INTO permissions (id, code, name, description, module, scope, is_active, created_at, updated_at)
                VALUES (:id, :code, :name, :desc, :module, :scope, :is_active, :now, :now)
            """),
            {
                "id": pid,
                "code": code,
                "name": name,
                "desc": desc,
                "module": module,
                "scope": scope,
                "is_active": True,
                "now": now,
            },
        )

    # 6. Asignar permisos a roles:
    # 26, 27, 28, 29, 32 -> platform_admin
    # 30, 31 -> admin y superadmin
    plat_role_ids = bind.scalars(
        sa.text("SELECT id FROM roles WHERE code = 'platform_admin' OR id = :rid"),
        {"rid": ROLE_PLATFORM_ADMIN},
    ).all()
    for plat_rid in plat_role_ids:
        for pnum in ("26", "27", "28", "29", "32"):
            pid = UUID(f"20000000-0000-0000-0000-0000000000{pnum}")
            exists = bind.scalar(
                sa.text("SELECT 1 FROM role_permissions WHERE role_id = :rid AND permission_id = :pid"),
                {"rid": plat_rid, "pid": pid},
            )
            if not exists:
                bind.execute(
                    sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:rid, :pid)"),
                    {"rid": plat_rid, "pid": pid},
                )

    admin_role_ids = bind.scalars(
        sa.text("SELECT id FROM roles WHERE code IN ('admin', 'superadmin') OR id IN (:r1, :r2)"),
        {"r1": ROLE_ADMIN, "r2": ROLE_SUPERADMIN},
    ).all()
    for adm_rid in admin_role_ids:
        for pnum in ("30", "31"):
            pid = UUID(f"20000000-0000-0000-0000-0000000000{pnum}")
            exists = bind.scalar(
                sa.text("SELECT 1 FROM role_permissions WHERE role_id = :rid AND permission_id = :pid"),
                {"rid": adm_rid, "pid": pid},
            )
            if not exists:
                bind.execute(
                    sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:rid, :pid)"),
                    {"rid": adm_rid, "pid": pid},
                )

    # 7. Renombrar roles para eliminar ambiguedad con la plataforma
    bind.execute(sa.text("""
        UPDATE roles
        SET name = 'Propietario de empresa', description = 'Control completo de su empresa.'
        WHERE code = 'superadmin'
    """))
    bind.execute(sa.text("""
        UPDATE roles
        SET name = 'Administrador de empresa'
        WHERE code = 'admin'
    """))


def downgrade() -> None:
    bind = op.get_bind()

    # Revertir nombres de roles
    bind.execute(sa.text("UPDATE roles SET name = 'Superadministrador' WHERE code = 'superadmin'"))
    bind.execute(sa.text("UPDATE roles SET name = 'Administrador' WHERE code = 'admin'"))

    # Borrar permisos nuevos de role_permissions y permissions
    new_perm_ids = [UUID(p[0]) for p in NEW_PERMISSIONS]
    for pid in new_perm_ids:
        bind.execute(sa.text("DELETE FROM role_permissions WHERE permission_id = :pid"), {"pid": pid})
        bind.execute(sa.text("DELETE FROM permissions WHERE id = :pid"), {"pid": pid})

    # Revertir audit_events
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_index("ix_audit_events_support_session_id")
        batch.drop_index("ix_audit_events_tenant_id")
        batch.drop_constraint("fk_audit_events_support_session_id_support_sessions", type_="foreignkey")
        batch.drop_constraint("fk_audit_events_tenant_id_tenants", type_="foreignkey")
        batch.drop_column("support_session_id")
        batch.drop_column("tenant_id")

    # Revertir permissions
    with op.batch_alter_table("permissions") as batch:
        batch.drop_constraint("ck_permissions_scope", type_="check")
        batch.drop_column("scope")

    # Revertir roles
    op.drop_index("uq_roles_system_code", "roles")
    with op.batch_alter_table("roles") as batch:
        batch.drop_constraint("uq_roles_tenant_code", type_="unique")
        batch.create_unique_constraint("uq_roles_code", ["code"])
        batch.drop_index("ix_roles_tenant_id")
        batch.drop_constraint("fk_roles_tenant_id_tenants", type_="foreignkey")
        batch.drop_column("tenant_id")

    # Borrar support_sessions
    op.drop_table("support_sessions")
