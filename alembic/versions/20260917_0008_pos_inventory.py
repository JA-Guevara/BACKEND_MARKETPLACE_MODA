"""Ventas presenciales y libro de movimientos de inventario."""
from alembic import op
import sqlalchemy as sa

revision = "20260917_0008"
down_revision = "20260916_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("commerce_orders", "user_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("commerce_orders", sa.Column("sales_channel", sa.String(10), nullable=False, server_default="web"))
    op.add_column("commerce_orders", sa.Column("cash_point_id", sa.Uuid(), nullable=True))
    op.add_column("commerce_orders", sa.Column("cashier_user_id", sa.Uuid(), nullable=True))
    op.add_column("commerce_orders", sa.Column("client_request_id", sa.Uuid(), nullable=True))
    op.add_column("commerce_orders", sa.Column("request_fingerprint", sa.String(64), nullable=True))
    op.create_foreign_key("fk_commerce_orders_cash_point_id_cash_points", "commerce_orders", "cash_points", ["cash_point_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_commerce_orders_cashier_user_id_users", "commerce_orders", "users", ["cashier_user_id"], ["id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_commerce_orders_client_request_id", "commerce_orders", ["client_request_id"])
    op.create_table(
        "commerce_stock_movements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("branch_id", sa.Uuid(), sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("quantity_before", sa.Integer(), nullable=False),
        sa.Column("quantity_after", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_email", sa.String(320), nullable=True),
        sa.CheckConstraint("quantity_before >= 0 AND quantity_after >= 0", name="nonnegative_balances"),
        sa.CheckConstraint("quantity_after = quantity_before + delta", name="balanced_movement"),
    )
    op.create_index("ix_commerce_stock_movements_variant_id", "commerce_stock_movements", ["variant_id"])
    op.create_index("ix_commerce_stock_movements_branch_id", "commerce_stock_movements", ["branch_id"])


def downgrade():
    # Guest sales cannot be represented in the previous NOT NULL schema.
    # Refuse destructive downgrade instead of deleting sales or inventing owners.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM commerce_orders WHERE user_id IS NULL LIMIT 1")).first():
        raise RuntimeError("Hay ventas de mostrador sin cuenta. Respaldar y resolver su propiedad antes de revertir.")
    op.drop_table("commerce_stock_movements")
    op.drop_constraint("uq_commerce_orders_client_request_id", "commerce_orders", type_="unique")
    op.drop_constraint("fk_commerce_orders_cashier_user_id_users", "commerce_orders", type_="foreignkey")
    op.drop_constraint("fk_commerce_orders_cash_point_id_cash_points", "commerce_orders", type_="foreignkey")
    for column in ["request_fingerprint", "client_request_id", "cashier_user_id", "cash_point_id", "sales_channel"]:
        op.drop_column("commerce_orders", column)
    op.alter_column("commerce_orders", "user_id", existing_type=sa.Uuid(), nullable=False)
