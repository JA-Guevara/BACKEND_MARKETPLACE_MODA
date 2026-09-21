"""Tabla de trabajos de foto IA realista del probador (Fase 3).

Revision ID: 20260920_0014
Revises: 20260920_0013
"""
from alembic import op
import sqlalchemy as sa

revision = "20260920_0014"
down_revision = "20260920_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tryon_ai_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("color_id", sa.Uuid(), nullable=True),
        sa.Column("garment_type", sa.String(length=40), nullable=True),
        sa.Column("body_region", sa.String(length=20), nullable=True),
        sa.Column("person_photo_url", sa.String(length=1000), nullable=False),
        sa.Column("garment_image_url", sa.String(length=1000), nullable=False),
        sa.Column("result_url", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_simulation", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["color_id"], ["colors.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tryon_ai_jobs_user_id", "tryon_ai_jobs", ["user_id"])
    op.create_index("ix_tryon_ai_jobs_product_id", "tryon_ai_jobs", ["product_id"])
    op.create_index("ix_tryon_ai_jobs_status", "tryon_ai_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_tryon_ai_jobs_status", table_name="tryon_ai_jobs")
    op.drop_index("ix_tryon_ai_jobs_product_id", table_name="tryon_ai_jobs")
    op.drop_index("ix_tryon_ai_jobs_user_id", table_name="tryon_ai_jobs")
    op.drop_table("tryon_ai_jobs")