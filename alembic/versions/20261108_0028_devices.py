"""Dispositivos y auditoría del tenant (CU-12).

Revision ID: 20261108_0028
Revises: 20261108_0027
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "20261108_0028"
down_revision: str | None = "20261108_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = [
    (
        "20000000-0000-0000-0000-000000000045",
        "devices.read",
        "Consultar dispositivos",
        "Ver terminales PWA y Android que sincronizan con la empresa",
        "devices_audit",
        "tenant",
    ),
    (
        "20000000-0000-0000-0000-000000000046",
        "devices.write",
        "Administrar dispositivos",
        "Bloquear, reactivar y etiquetar terminales de la empresa",
        "devices_audit",
        "tenant",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    # 1. Crear tabla devices
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=10), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("branch_id", sa.Uuid(), nullable=True),
        sa.Column("app_version", sa.String(length=40), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_snapshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_batch_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="ACTIVO", nullable=False),
        sa.Column("blocked_by", sa.Uuid(), nullable=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("block_reason", sa.Text(), nullable=True),
        sa.Column("rejected_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("platform IN ('PWA', 'ANDROID')", name="ck_devices_platform"),
        sa.CheckConstraint("status IN ('ACTIVO', 'BLOQUEADO')", name="ck_devices_status"),
        sa.ForeignKeyConstraint(["blocked_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "device_id", name="uq_devices_tenant_device"),
    )
    op.create_index("ix_devices_tenant_id", "devices", ["tenant_id"])
    op.create_index("ix_devices_user_id", "devices", ["user_id"])
    op.create_index("ix_devices_branch_id", "devices", ["branch_id"])
    op.create_index("ix_devices_tenant_status", "devices", ["tenant_id", "status"])
    op.create_index("ix_devices_tenant_last_sync", "devices", ["tenant_id", "last_sync_at"])

    # 2. Permisos y módulo devices_audit
    perm_table = sa.table(
        "permissions",
        sa.column("id", sa.Uuid),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("module", sa.String),
        sa.column("scope", sa.String),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )

    for pid, code, name, desc, mod, scope in NEW_PERMISSIONS:
        exists = bind.execute(sa.select(perm_table.c.id).where(perm_table.c.code == code)).scalar_one_or_none()
        if not exists:
            op.bulk_insert(
                perm_table,
                [
                    {
                        "id": uuid.UUID(pid),
                        "code": code,
                        "name": name,
                        "description": desc,
                        "module": mod,
                        "scope": scope,
                        "created_at": now,
                        "updated_at": now,
                    }
                ],
            )

    inspector = sa.inspect(bind)

    # 4. Asignar permisos a roles de administrador
    roles_table = sa.table(
        "roles",
        sa.column("id", sa.Uuid),
        sa.column("name", sa.String),
        sa.column("is_system", sa.Boolean),
    )
    role_perm_table = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Uuid),
        sa.column("permission_id", sa.Uuid),
    )

    admin_roles = bind.execute(
        sa.select(roles_table.c.id).where(roles_table.c.name.in_(["Administrador", "Admin", "admin", "SUPERADMIN"]))
    ).scalars().all()

    for r_id in admin_roles:
        for pid, _, _, _, _, _ in NEW_PERMISSIONS:
            p_uuid = uuid.UUID(pid)
            assigned = bind.execute(
                sa.select(role_perm_table.c.role_id).where(
                    role_perm_table.c.role_id == r_id,
                    role_perm_table.c.permission_id == p_uuid,
                )
            ).scalar_one_or_none()
            if not assigned:
                op.bulk_insert(role_perm_table, [{"role_id": r_id, "permission_id": p_uuid}])

    # 5. Índices en audit_events si no existen
    if "audit_events" in inspector.get_table_names():
        audit_indexes = [idx["name"] for idx in inspector.get_indexes("audit_events")]
        if "ix_audit_events_tenant_created" not in audit_indexes:
            op.create_index("ix_audit_events_tenant_created", "audit_events", ["tenant_id", "created_at"])
        if "ix_audit_events_tenant_entity" not in audit_indexes:
            op.create_index("ix_audit_events_tenant_entity", "audit_events", ["tenant_id", "entity_type"])


    # Integración RS2: permisos vinculados al módulo que regula el acceso.
    bind = op.get_bind()
    if "module_permissions" in sa.inspect(bind).get_table_names():
        association = sa.table("module_permissions", sa.column("module_code", sa.String()), sa.column("permission_id", sa.Uuid()))
        permission = sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String()))
        for permission_code in ['devices.read', 'devices.write']:
            permission_id = bind.scalar(sa.select(permission.c.id).where(permission.c.code == permission_code))
            if permission_id is not None:
                bind.execute(association.insert().values(module_code='devices_audit', permission_id=permission_id))


def downgrade() -> None:
    op.drop_index("ix_devices_tenant_last_sync", table_name="devices")
    op.drop_index("ix_devices_tenant_status", table_name="devices")
    op.drop_index("ix_devices_branch_id", table_name="devices")
    op.drop_index("ix_devices_user_id", table_name="devices")
    op.drop_index("ix_devices_tenant_id", table_name="devices")
    op.drop_table("devices")
