"""Código postal y país en las direcciones del cliente.

El pedido ya pedía ambos datos, pero la dirección guardada no los tenía, así que
el cliente debía reescribirlos en cada compra. Ambas columnas son aditivas: las
filas existentes quedan con país "BO" y sin código postal.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260912_0004"
down_revision = "20260910_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_addresses", sa.Column("postal_code", sa.String(length=20), nullable=True))
    op.add_column(
        "user_addresses",
        sa.Column("country", sa.String(length=2), nullable=False, server_default="BO"),
    )


def downgrade():
    op.drop_column("user_addresses", "country")
    op.drop_column("user_addresses", "postal_code")
