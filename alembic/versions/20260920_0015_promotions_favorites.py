"""Cupones, promociones y favoritos con alertas.

Revision ID: 20260920_0015
Revises: 20260920_0014
"""
from alembic import op
import sqlalchemy as sa

revision = "20260920_0015"
down_revision = "20260920_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("commerce_orders", sa.Column("subtotal", sa.Numeric(12, 2), nullable=False, server_default="0"))
    op.add_column("commerce_orders", sa.Column("discount_total", sa.Numeric(12, 2), nullable=False, server_default="0"))
    op.add_column("commerce_orders", sa.Column("discounts", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("commerce_orders", sa.Column("coupon_code", sa.String(length=50), nullable=True))
    op.create_table(
        "commerce_promotions",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False), sa.Column("code", sa.String(length=50), nullable=True), sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("discount_type", sa.String(length=20), nullable=False), sa.Column("discount_value", sa.Numeric(12, 2), nullable=False, server_default="0"), sa.Column("minimum_order", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("category_id", sa.Uuid(), nullable=True), sa.Column("product_id", sa.Uuid(), nullable=True), sa.Column("customer_scope", sa.String(length=20), nullable=False, server_default="all"), sa.Column("minimum_paid_orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True), sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True), sa.Column("max_uses", sa.Integer(), nullable=True), sa.Column("uses_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("per_user_limit", sa.Integer(), nullable=True), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("discount_value >= 0", name="promotion_value_nonnegative"), sa.CheckConstraint("minimum_order >= 0", name="promotion_minimum_nonnegative"), sa.CheckConstraint("max_uses IS NULL OR max_uses > 0", name="promotion_max_uses_positive"), sa.CheckConstraint("per_user_limit IS NULL OR per_user_limit > 0", name="promotion_per_user_positive"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("code"),
    )
    op.create_index("ix_commerce_promotions_code", "commerce_promotions", ["code"]); op.create_index("ix_commerce_promotions_category_id", "commerce_promotions", ["category_id"]); op.create_index("ix_commerce_promotions_product_id", "commerce_promotions", ["product_id"]); op.create_index("ix_commerce_promotions_starts_at", "commerce_promotions", ["starts_at"]); op.create_index("ix_commerce_promotions_ends_at", "commerce_promotions", ["ends_at"]); op.create_index("ix_commerce_promotions_is_active", "commerce_promotions", ["is_active"])
    op.create_table(
        "commerce_promotion_uses",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("promotion_id", sa.Uuid(), nullable=False), sa.Column("user_id", sa.Uuid(), nullable=False), sa.Column("order_id", sa.Uuid(), nullable=False), sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(["promotion_id"], ["commerce_promotions.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["order_id"], ["commerce_orders.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("promotion_id", "order_id"),
    )
    op.create_index("ix_commerce_promotion_uses_promotion_id", "commerce_promotion_uses", ["promotion_id"]); op.create_index("ix_commerce_promotion_uses_user_id", "commerce_promotion_uses", ["user_id"]); op.create_index("ix_commerce_promotion_uses_order_id", "commerce_promotion_uses", ["order_id"])
    op.create_table(
        "commerce_favorites",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False), sa.Column("product_id", sa.Uuid(), nullable=False), sa.Column("stock_alert", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("price_alert", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("observed_price", sa.Numeric(12, 2), nullable=False), sa.Column("last_stock_alert_at", sa.DateTime(timezone=True), nullable=True), sa.Column("last_price_alert_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("user_id", "product_id"),
    )
    op.create_index("ix_commerce_favorites_user_id", "commerce_favorites", ["user_id"]); op.create_index("ix_commerce_favorites_product_id", "commerce_favorites", ["product_id"])


def downgrade() -> None:
    op.drop_table("commerce_favorites"); op.drop_table("commerce_promotion_uses"); op.drop_table("commerce_promotions")
    op.drop_column("commerce_orders", "coupon_code"); op.drop_column("commerce_orders", "discounts"); op.drop_column("commerce_orders", "discount_total"); op.drop_column("commerce_orders", "subtotal")
