"""Recurso preparado del probador virtual, por producto y color.

Aditiva: crea una tabla nueva y no altera las existentes. El recurso se asocia
al color porque la foto cambia con el color pero no con la talla.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260917_0010"
down_revision = "20260917_0009"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade():
    op.create_table(
        "virtual_tryon_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("color_id", sa.Uuid(), sa.ForeignKey("colors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("mode", sa.String(length=10), nullable=False, server_default="2.5d"),
        sa.Column("source_image_url", sa.String(length=1000), nullable=False),
        sa.Column("transparent_url", sa.String(length=1000)),
        sa.Column("mask_url", sa.String(length=1000)),
        sa.Column("model_3d_url", sa.String(length=1000)),
        sa.Column("garment_type", sa.String(length=40)),
        sa.Column("body_region", sa.String(length=20)),
        sa.Column("anchor_points", JSON_TYPE),
        sa.Column("ai_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("ai_metadata", JSON_TYPE),
        sa.Column("ai_error", sa.Text()),
        sa.UniqueConstraint("product_id", "color_id", name="tryon_producto_color"),
    )
    op.create_index("ix_virtual_tryon_assets_product_id", "virtual_tryon_assets", ["product_id"])
    op.create_index("ix_virtual_tryon_assets_color_id", "virtual_tryon_assets", ["color_id"])
    op.create_index("ix_virtual_tryon_assets_body_region", "virtual_tryon_assets", ["body_region"])


def downgrade():
    op.drop_index("ix_virtual_tryon_assets_body_region", table_name="virtual_tryon_assets")
    op.drop_index("ix_virtual_tryon_assets_color_id", table_name="virtual_tryon_assets")
    op.drop_index("ix_virtual_tryon_assets_product_id", table_name="virtual_tryon_assets")
    op.drop_table("virtual_tryon_assets")
