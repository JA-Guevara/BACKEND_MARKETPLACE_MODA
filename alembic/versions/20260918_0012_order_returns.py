"""Devoluciones de pedidos (CU19).

Aditiva: crea una tabla nueva y no altera las existentes. El detalle se guarda
como copia porque el precio del catálogo puede cambiar después de la compra.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260918_0012"
down_revision = "20260918_0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commerce_order_returns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("commerce_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("branch_id", sa.Uuid(), sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="requested"),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("refund_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("resolution_note", sa.String(length=500), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("client_request_id", sa.Uuid(), nullable=True, unique=True),
    )
    op.create_index("ix_commerce_order_returns_order_id", "commerce_order_returns", ["order_id"])
    op.create_index("ix_commerce_order_returns_user_id", "commerce_order_returns", ["user_id"])
    op.create_index("ix_commerce_order_returns_branch_id", "commerce_order_returns", ["branch_id"])
    op.create_index("ix_commerce_order_returns_status", "commerce_order_returns", ["status"])


def downgrade():
    op.drop_table("commerce_order_returns")
