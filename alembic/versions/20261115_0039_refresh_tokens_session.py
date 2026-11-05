"""Datos de sesion y auditoria en refresh_tokens (PX-1.5).

Revision ID: 20261115_0039
Revises: 20261115_0038
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261115_0039"
down_revision: str | None = "20261115_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("refresh_tokens")}

    if "device_label" not in cols:
        op.add_column("refresh_tokens", sa.Column("device_label", sa.String(100), nullable=True))
    if "user_agent" not in cols:
        op.add_column("refresh_tokens", sa.Column("user_agent", sa.String(255), nullable=True))
    if "ip_prefix" not in cols:
        op.add_column("refresh_tokens", sa.Column("ip_prefix", sa.String(45), nullable=True))
    if "last_used_at" not in cols:
        op.add_column("refresh_tokens", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("refresh_tokens")}

    if "last_used_at" in cols:
        op.drop_column("refresh_tokens", "last_used_at")
    if "ip_prefix" in cols:
        op.drop_column("refresh_tokens", "ip_prefix")
    if "user_agent" in cols:
        op.drop_column("refresh_tokens", "user_agent")
    if "device_label" in cols:
        op.drop_column("refresh_tokens", "device_label")
