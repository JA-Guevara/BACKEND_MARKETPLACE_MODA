"""Add paid_at to commerce_orders (fecha efectiva del cobro)."""
from alembic import op
import sqlalchemy as sa

revision = "20260916_0007"
down_revision = "20260916_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("commerce_orders", sa.Column("paid_at", sa.DateTime(), nullable=True))
    op.create_index("ix_commerce_orders_paid_at", "commerce_orders", ["paid_at"])


def downgrade():
    op.drop_index("ix_commerce_orders_paid_at", table_name="commerce_orders")
    op.drop_column("commerce_orders", "paid_at")