"""Estado de cuenta con comprobantes de suscripción simulados (PX-1.1).

Revision ID: 20261115_0037
Revises: 20261110_0036
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "20261115_0037"
down_revision: str | None = "20261110_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_PERMISSIONS = [
    (
        "20000000-0000-0000-0000-000000000062",
        "billing.read",
        "Consultar facturación y estado de cuenta",
        "Ver comprobantes de suscripción y estado de cuenta de la empresa",
        "billing",
        "tenant",
    ),
]


def _table_exists(bind, table_name: str) -> bool:
    insp = sa.inspect(bind)
    return table_name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    now_utc = datetime.now(timezone.utc)

    # 1. Crear tabla subscription_invoices si no existe
    if not _table_exists(bind, "subscription_invoices"):
        op.create_table(
            "subscription_invoices",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("number", sa.String(length=32), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("subscription_id", sa.Uuid(), sa.ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="BOB"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="issued"),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("paid_reference", sa.String(length=80), nullable=True),
            sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.UniqueConstraint("number", name="uq_subscription_invoices_number"),
            sa.UniqueConstraint("subscription_id", "period_start", name="uq_subscription_invoices_sub_period"),
        )
        op.create_index(
            "ix_subscription_invoices_tenant_id",
            "subscription_invoices",
            ["tenant_id"],
        )
        op.create_index(
            "ix_subscription_invoices_subscription_id",
            "subscription_invoices",
            ["subscription_id"],
        )

    # 2. Sembrar permiso 062 billing.read
    for pid_str, code, name, desc, module_name, scope in NEW_PERMISSIONS:
        perm_uuid = uuid.UUID(pid_str)

        existing_by_code = bind.execute(
            sa.text("SELECT id FROM permissions WHERE code = :code"),
            {"code": code},
        ).scalar()
        if existing_by_code:
            continue

        existing_by_id = bind.execute(
            sa.text("SELECT code FROM permissions WHERE id = :id"),
            {"id": perm_uuid},
        ).scalar()
        if existing_by_id and existing_by_id != code:
            raise RuntimeError(
                f"ID {pid_str} ocupado por otro código ({existing_by_id}). La migración falla por contrato."
            )

        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, name, description, module, scope, is_active, created_at, updated_at) "
                "VALUES (:id, :code, :name, :description, :module, :scope, :is_active, :now, :now)"
            ),
            {
                "id": perm_uuid,
                "code": code,
                "name": name,
                "description": desc,
                "module": module_name,
                "scope": scope,
                "is_active": True,
                "now": now_utc,
            },
        )

    # 3. Asignar billing.read a roles de administrador de empresa
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r, permissions p "
            "WHERE r.code IN ('admin', 'superadmin') AND r.audience = 'TENANT' "
            "AND p.code = 'billing.read' "
            "AND NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
        )
    )

    # 4. Asignar a plantillas si existen roles template con tenant_id IS NULL
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r, permissions p "
            "WHERE r.tenant_id IS NULL AND r.code IN ('admin', 'superadmin') "
            "AND p.code = 'billing.read' "
            "AND NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Quitar asignaciones del permiso
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN ("
            "  SELECT id FROM permissions WHERE code = 'billing.read'"
            ")"
        )
    )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE code = 'billing.read'")
    )

    if _table_exists(bind, "subscription_invoices"):
        op.drop_table("subscription_invoices")
