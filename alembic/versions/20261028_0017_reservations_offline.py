"""Origen y actor de las reservas creadas sin conexión."""
from alembic import op
import sqlalchemy as sa

revision = "20261028_0017"
down_revision = "20261024_0016"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("reservations") as batch:
        batch.add_column(sa.Column("origin", sa.String(10), nullable=False, server_default="ONLINE"))
        batch.add_column(sa.Column("device_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("client_created_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("created_by_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_reservations_created_by_id_users", "users", ["created_by_id"], ["id"])


def downgrade():
    with op.batch_alter_table("reservations") as batch:
        batch.drop_constraint("fk_reservations_created_by_id_users", type_="foreignkey")
        for column in ("created_by_id", "client_created_at", "device_id", "origin"):
            batch.drop_column(column)
