"""Calidad y revisión del recurso del probador (plan de evolución, Fase 1).

Aditiva: agrega al recurso los campos con los que se decide qué se publica solo
(ready), qué espera aprobación (review) y qué queda marcado fallido. No toca las
filas existentes: los recursos ya listos siguen listos.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260920_0013"
down_revision = "20260918_0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "virtual_tryon_assets",
        sa.Column("quality_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "virtual_tryon_assets",
        sa.Column("quality_reason", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "virtual_tryon_assets",
        sa.Column("preview_url", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "virtual_tryon_assets",
        sa.Column(
            "reviewed_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_virtual_tryon_assets_reviewed_by", "virtual_tryon_assets", ["reviewed_by"]
    )


def downgrade():
    op.drop_index("ix_virtual_tryon_assets_reviewed_by", table_name="virtual_tryon_assets")
    op.drop_column("virtual_tryon_assets", "reviewed_by")
    op.drop_column("virtual_tryon_assets", "preview_url")
    op.drop_column("virtual_tryon_assets", "quality_reason")
    op.drop_column("virtual_tryon_assets", "quality_score")