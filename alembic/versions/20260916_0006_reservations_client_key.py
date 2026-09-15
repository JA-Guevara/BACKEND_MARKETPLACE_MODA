"""Add idempotency client_key to reservations."""
import uuid
from alembic import op
import sqlalchemy as sa

revision = "20260916_0006"
down_revision = "20260912_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("reservations", sa.Column("client_key", sa.String(64), nullable=True))
    op.create_unique_constraint(
        "uq_reservations_user_client_key", "reservations", ["user_id", "client_key"]
    )


def downgrade():
    op.drop_constraint("uq_reservations_user_client_key", "reservations", type_="unique")
    op.drop_column("reservations", "client_key")