"""Correo de la sucursal para los avisos de reserva (RF11).

Aditiva y reversible: agrega una columna opcional. Las sucursales que no la
completen siguen funcionando; sus avisos van a la casilla de operaciones.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260918_0011"
down_revision = "20260917_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("branches", sa.Column("notification_email", sa.String(length=320), nullable=True))


def downgrade():
    op.drop_column("branches", "notification_email")
