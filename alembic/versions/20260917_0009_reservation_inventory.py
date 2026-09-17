"""Track inventory held by new reservations without altering legacy stock."""
from alembic import op
import sqlalchemy as sa

revision = "20260917_0009"
down_revision = "20260917_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("reservations", sa.Column("inventory_held", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("reservations", "inventory_held")
