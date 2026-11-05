"""Ciclo de vida de la suscripción, solo lectura y tareas programadas (PX-0.4).

Revision ID: 20261110_0036
Revises: 20261110_0035
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "20261110_0036"
down_revision: str | None = "20261110_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    insp = sa.inspect(bind)
    return table_name in insp.get_table_names()


def _column_names(bind, table_name: str) -> set[str]:
    if not _table_exists(bind, table_name):
        return set()
    insp = sa.inspect(bind)
    return {col["name"] for col in insp.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Agregar columnas a subscriptions si no existen
    sub_cols = _column_names(bind, "subscriptions")
    if "grace_until" not in sub_cols:
        op.add_column("subscriptions", sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True))
    if "read_only_since" not in sub_cols:
        op.add_column("subscriptions", sa.Column("read_only_since", sa.DateTime(timezone=True), nullable=True))
    if "canceled_at" not in sub_cols:
        op.add_column("subscriptions", sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True))
    if "data_retention_until" not in sub_cols:
        op.add_column("subscriptions", sa.Column("data_retention_until", sa.DateTime(timezone=True), nullable=True))

    # 2. Crear tabla job_runs si no existe
    if not _table_exists(bind, "job_runs"):
        op.create_table(
            "job_runs",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("job", sa.String(length=60), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="ok"),
            sa.Column(
                "changes",
                sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
                nullable=True,
            ),
            sa.Column("error", sa.Text(), nullable=True),
        )
        op.create_index(
            "ix_job_runs_job_started_at",
            "job_runs",
            ["job", sa.text("started_at DESC")],
        )

    # 3. Crear tabla subscription_notices si no existe
    if not _table_exists(bind, "subscription_notices"):
        op.create_table(
            "subscription_notices",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("subscription_id", sa.Uuid(), sa.ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(length=30), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("subscription_id", "kind", "period_end", name="uq_subscription_notices_kind_end"),
        )
        op.create_index(
            "ix_subscription_notices_subscription_id",
            "subscription_notices",
            ["subscription_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "subscription_notices"):
        op.drop_table("subscription_notices")

    if _table_exists(bind, "job_runs"):
        op.drop_table("job_runs")

    with op.batch_alter_table("subscriptions") as batch:
        batch.drop_column("data_retention_until")
        batch.drop_column("canceled_at")
        batch.drop_column("read_only_since")
        batch.drop_column("grace_until")
