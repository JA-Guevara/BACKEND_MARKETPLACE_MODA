"""Ventas sin conexión y asignación de usuarios a sucursales.

Revision ID: 20261106_0022
Revises: 20261105_0021
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261106_0022"
down_revision: str | None = "20261104_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Campos para ventas offline en commerce_orders
    op.add_column(
        "commerce_orders",
        sa.Column("origin", sa.String(10), nullable=False, server_default="ONLINE"),
    )
    op.add_column(
        "commerce_orders",
        sa.Column("device_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "commerce_orders",
        sa.Column("client_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "commerce_orders",
        sa.Column("local_folio", sa.String(30), nullable=True),
    )
    op.add_column(
        "commerce_orders",
        sa.Column("cash_received", sa.Numeric(12, 2), nullable=True),
    )
    op.create_index(
        "ix_commerce_orders_origin",
        "commerce_orders",
        ["tenant_id", "origin", "created_at"],
    )

    # 2. Tabla user_branches
    op.create_table(
        "user_branches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)),
        sa.UniqueConstraint("user_id", "branch_id", name="uq_user_branches_user_branch"),
    )


def downgrade() -> None:
    op.drop_table("user_branches")
    op.drop_index("ix_commerce_orders_origin", table_name="commerce_orders")
    op.drop_column("commerce_orders", "cash_received")
    op.drop_column("commerce_orders", "local_folio")
    op.drop_column("commerce_orders", "client_created_at")
    op.drop_column("commerce_orders", "device_id")
    op.drop_column("commerce_orders", "origin")
