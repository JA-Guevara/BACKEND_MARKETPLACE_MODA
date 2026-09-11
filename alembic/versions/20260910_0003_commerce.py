"""Commerce stock, carts, orders and verified payment events."""
import uuid
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa

revision = "20260910_0003"
down_revision = "20260905_0002"
branch_labels = None
depends_on = None

PERMISSIONS = ["commerce.read", "commerce.write", "stock.read", "stock.write", "dashboard.read"]
IDS = [uuid.UUID(f"20000000-0000-0000-0000-{n:012d}") for n in range(12, 17)]

def columns():
    return [sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]

def upgrade():
    op.create_table("commerce_stock", *columns(),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("branch_id", sa.Uuid(), sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("quantity >= 0", name="quantity_positive"), sa.UniqueConstraint("variant_id", "branch_id"))
    op.create_table("commerce_cart_items", *columns(),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"), sa.UniqueConstraint("user_id", "variant_id"))
    op.create_index("ix_commerce_cart_items_user_id", "commerce_cart_items", ["user_id"])
    op.create_table("commerce_orders", *columns(),
        sa.Column("number", sa.String(40), nullable=False, unique=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("branch_id", sa.Uuid(), sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("customer_email", sa.String(320), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending_payment"),
        sa.Column("payment_status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("payment_method", sa.String(30), nullable=False),
        sa.Column("payment_reference", sa.String(255)),
        sa.Column("total", sa.Numeric(12,2), nullable=False), sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("address", sa.JSON(), nullable=False), sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("tracking", sa.JSON(), nullable=False), sa.Column("carrier", sa.String(120)),
        sa.Column("tracking_number", sa.String(150)), sa.Column("stripe_session_id", sa.String(255), unique=True),
        sa.Column("stripe_url", sa.String(2000)))
    op.create_index("ix_commerce_orders_user_id", "commerce_orders", ["user_id"])
    op.create_index("ix_commerce_orders_status", "commerce_orders", ["status"])
    op.create_table("commerce_webhook_events", *columns(), sa.Column("event_id", sa.String(255), nullable=False, unique=True))
    permissions = sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String()),
        sa.column("name", sa.String()), sa.column("module", sa.String()), sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)))
    now = datetime.now(timezone.utc)
    op.bulk_insert(permissions, [dict(id=pid, code=code, name=code, module=code.split('.')[0], is_active=True, created_at=now, updated_at=now) for pid, code in zip(IDS, PERMISSIONS)])
    links = sa.table("role_permissions", sa.column("role_id", sa.Uuid()), sa.column("permission_id", sa.Uuid()))
    op.bulk_insert(links, [dict(role_id=uuid.UUID(f"10000000-0000-0000-0000-{n:012d}"), permission_id=pid) for n in (1,2) for pid in IDS])

def downgrade():
    for name in ("role_permissions", "permissions"):
        key = "permission_id" if name == "role_permissions" else "id"
        table = sa.table(name, sa.column(key, sa.Uuid()))
        op.execute(table.delete().where(table.c[key].in_(IDS)))
    for name in ("commerce_webhook_events", "commerce_orders", "commerce_cart_items", "commerce_stock"):
        op.drop_table(name)
