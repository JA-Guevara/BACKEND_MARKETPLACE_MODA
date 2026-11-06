"""Conserva la cuenta Stripe original de cada pedido.

Revision ID: 20261124_0043
Revises: 20261123_0042
"""
from alembic import op
import sqlalchemy as sa

revision = "20261124_0043"
down_revision = "20261123_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("commerce_orders", sa.Column("stripe_account_id", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("commerce_orders", "stripe_account_id")
