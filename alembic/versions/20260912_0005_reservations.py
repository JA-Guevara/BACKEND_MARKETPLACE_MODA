"""Reservations for trying garments in-store (RF09-RF12)."""
import uuid
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa

revision = "20260912_0005"
down_revision = "20260912_0004"
branch_labels = None
depends_on = None

PERMISSIONS = ["reservations.read", "reservations.write"]
IDS = [uuid.UUID(f"20000000-0000-0000-0000-{n:012d}") for n in range(17, 19)]
ADMIN_ROLE_IDS = [uuid.UUID(f"10000000-0000-0000-0000-{n:012d}") for n in (1, 2, 3)]  # superadmin, admin, store_manager


def upgrade():
    op.create_table(
        "reservations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch_id", sa.Uuid(), sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("notes", sa.String(1000)),
        sa.Column("tracking", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_reservations_user_id", "reservations", ["user_id"])
    op.create_index("ix_reservations_branch_id", "reservations", ["branch_id"])
    op.create_index("ix_reservations_status", "reservations", ["status"])
    permissions = sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String()),
        sa.column("name", sa.String()), sa.column("module", sa.String()), sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)))
    now = datetime.now(timezone.utc)
    op.bulk_insert(permissions, [dict(id=pid, code=code, name=code, module=code.split('.')[0], is_active=True, created_at=now, updated_at=now) for pid, code in zip(IDS, PERMISSIONS)])
    links = sa.table("role_permissions", sa.column("role_id", sa.Uuid()), sa.column("permission_id", sa.Uuid()))
    op.bulk_insert(links, [dict(role_id=role_id, permission_id=pid) for role_id in ADMIN_ROLE_IDS for pid in IDS])


def downgrade():
    for name in ("role_permissions", "permissions"):
        key = "permission_id" if name == "role_permissions" else "id"
        table = sa.table(name, sa.column(key, sa.Uuid()))
        op.execute(table.delete().where(table.c[key].in_(IDS)))
    op.drop_table("reservations")
