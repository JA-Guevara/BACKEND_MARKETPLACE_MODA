"""Tablas de sincronización sin conexión y permisos 33-36.

Revision ID: 20261106_0023
Revises: 20261106_0022
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261106_0023"
down_revision: str | None = "20261106_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYNC_PERMISSIONS = [
    ("20000000-0000-0000-0000-000000000033", "sync.write", "Sincronizar operaciones", "Enviar lotes de sincronización sin conexión", "tenant", "tenant"),
    ("20000000-0000-0000-0000-000000000034", "sync_conflicts.read", "Consultar conflictos", "Ver lista y detalle de conflictos de sincronización", "tenant", "tenant"),
    ("20000000-0000-0000-0000-000000000035", "sync_conflicts.resolve", "Resolver conflictos", "Resolver conflictos de stock, precio y suscripción", "tenant", "tenant"),
    ("20000000-0000-0000-0000-000000000036", "sync_log.read", "Consultar bitácora sync", "Ver historial y detalle de lotes sincronizados", "tenant", "tenant"),
]

ROLE_ADMIN = uuid.UUID("10000000-0000-0000-0000-000000000002")
ROLE_STORE_MANAGER = uuid.UUID("10000000-0000-0000-0000-000000000003")
ROLE_CASHIER = uuid.UUID("10000000-0000-0000-0000-000000000004")
ROLE_CLIENT = uuid.UUID("10000000-0000-0000-0000-000000000005")


def upgrade() -> None:
    # 1. Columnas en commerce_orders
    op.add_column(
        "commerce_orders",
        sa.Column("price_authorized_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "commerce_orders",
        sa.Column("offline_adjustment", sa.JSON(), nullable=True),
    )

    # 2. sync_batches
    op.create_table(
        "sync_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflicts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("replays", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("client_version", sa.String(40), nullable=False, server_default=""),
        sa.Column("client_ip", sa.String(45), nullable=True),
        sa.Column("error_summary", sa.String(300), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_sync_batches_tenant_started",
        "sync_batches",
        ["tenant_id", "started_at"],
    )

    # 3. sync_operations
    op.create_table(
        "sync_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("client_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(12), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sync_batches.id", ondelete="CASCADE"), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("server_ref", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("server_number", sa.String(40), nullable=True),
        sa.Column("reason_code", sa.String(40), nullable=True),
        sa.Column("message", sa.String(300), nullable=False, server_default=""),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("tenant_id", "client_request_id", name="uq_sync_operations_tenant_request"),
    )
    op.create_index(
        "ix_sync_operations_status",
        "sync_operations",
        ["tenant_id", "status"],
    )

    # 4. sync_conflicts
    op.create_table(
        "sync_conflicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sync_operations.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="OPEN"),
        sa.Column("resolution", sa.String(20), nullable=True),
        sa.Column("resolution_note", sa.String(300), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_sync_conflicts_open",
        "sync_conflicts",
        ["tenant_id", "branch_id", "status"],
    )

    # 5. Permisos
    perm_table = sa.table(
        "permissions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("module", sa.String),
        sa.column("scope", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    for pid, code, name, desc, mod, scope in SYNC_PERMISSIONS:
        op.execute(
            perm_table.insert().values(
                id=uuid.UUID(pid),
                code=code,
                name=name,
                description=desc,
                module=mod,
                scope=scope,
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )

    # Asignaciones a roles
    rp_table = sa.table(
        "role_permissions",
        sa.column("role_id", postgresql.UUID(as_uuid=True)),
        sa.column("permission_id", postgresql.UUID(as_uuid=True)),
    )
    # 33 sync.write a cashier, store_manager, admin, client
    p33 = uuid.UUID("20000000-0000-0000-0000-000000000033")
    for rid in [ROLE_CASHIER, ROLE_STORE_MANAGER, ROLE_ADMIN, ROLE_CLIENT]:
        op.execute(rp_table.insert().values(role_id=rid, permission_id=p33))

    # 34, 35, 36 a store_manager y admin
    for pid_str in ["20000000-0000-0000-0000-000000000034", "20000000-0000-0000-0000-000000000035", "20000000-0000-0000-0000-000000000036"]:
        pid = uuid.UUID(pid_str)
        op.execute(rp_table.insert().values(role_id=ROLE_STORE_MANAGER, permission_id=pid))
        op.execute(rp_table.insert().values(role_id=ROLE_ADMIN, permission_id=pid))


    # Integración RS2: permisos vinculados al módulo que regula el acceso.
    bind = op.get_bind()
    if "module_permissions" in sa.inspect(bind).get_table_names():
        association = sa.table("module_permissions", sa.column("module_code", sa.String()), sa.column("permission_id", sa.Uuid()))
        permission = sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String()))
        for permission_code in ['sync.write', 'sync_conflicts.read', 'sync_conflicts.resolve', 'sync_log.read']:
            permission_id = bind.scalar(sa.select(permission.c.id).where(permission.c.code == permission_code))
            if permission_id is not None:
                bind.execute(association.insert().values(module_code='offline', permission_id=permission_id))


def downgrade() -> None:
    # Eliminar asignaciones de permisos
    for pid_str in ["20000000-0000-0000-0000-000000000033", "20000000-0000-0000-0000-000000000034", "20000000-0000-0000-0000-000000000035", "20000000-0000-0000-0000-000000000036"]:
        op.execute(f"DELETE FROM role_permissions WHERE permission_id = '{pid_str}'")
        op.execute(f"DELETE FROM permissions WHERE id = '{pid_str}'")

    op.drop_table("sync_conflicts")
    op.drop_table("sync_operations")
    op.drop_table("sync_batches")
    op.drop_column("commerce_orders", "offline_adjustment")
    op.drop_column("commerce_orders", "price_authorized_by")
