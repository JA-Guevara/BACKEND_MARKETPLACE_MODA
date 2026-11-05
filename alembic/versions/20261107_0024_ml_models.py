"""Modelos y tablas para Analítica predictiva y Machine Learning (CU-10)

Revision ID: 20261107_0024
Revises: 20261106_0023
Create Date: 2026-11-07 10:00:00.000000
"""

from datetime import datetime, timezone
from typing import Sequence, Union
import uuid
from alembic import op
import sqlalchemy as sa

revision: str = "20261107_0024"
down_revision: Union[str, None] = "20261106_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_training_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="RUNNING"),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ml_training_runs_tenant", "ml_training_runs", ["tenant_id"])

    op.create_table(
        "ml_models",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("model_type", sa.String(50), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("artifact", sa.LargeBinary(), nullable=False),
        sa.Column("artifact_bytes", sa.Integer(), nullable=False),
        sa.Column("artifact_sha256", sa.CHAR(64), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ml_models_tenant_active", "ml_models", ["tenant_id", "is_active"])

    op.create_table(
        "ml_predictions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_id", sa.String(36), sa.ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_date", sa.String(20), nullable=False),
        sa.Column("variant_id", sa.String(36), nullable=False),
        sa.Column("branch_id", sa.String(36), nullable=False),
        sa.Column("predicted_units", sa.Float(), nullable=False),
        sa.Column("actual_units", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ml_predictions_tenant_date", "ml_predictions", ["tenant_id", "target_date"])

    op.create_table(
        "ml_customer_segments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.String(36), nullable=False),
        sa.Column("segment_name", sa.String(100), nullable=False),
        sa.Column("recency_days", sa.Integer(), nullable=False),
        sa.Column("frequency_orders", sa.Integer(), nullable=False),
        sa.Column("monetary_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ml_customer_segments_tenant", "ml_customer_segments", ["tenant_id"])

    op.create_table(
        "ml_anomalies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch_id", sa.String(36), nullable=False),
        sa.Column("sale_date", sa.String(20), nullable=False),
        sa.Column("anomaly_score", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ml_anomalies_tenant_date", "ml_anomalies", ["tenant_id", "sale_date"])

    # Permisos
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    now = datetime.now(timezone.utc)
    ml_perms = [
        ("20000000-0000-0000-0000-000000000041", "ml_dashboard.read", "Ver tablero de predicciones y métricas de Machine Learning", "Ver tablero de predicciones", "analytics", "tenant"),
        ("20000000-0000-0000-0000-000000000042", "ml_models.manage", "Entrenar y gestionar modelos de Machine Learning", "Entrenar y gestionar modelos", "analytics", "platform"),
    ]
    for pid_str, code, desc, name, mod, scope in ml_perms:
        pid = pid_str if is_sqlite else uuid.UUID(pid_str)
        bind.execute(
            sa.text("""
                INSERT INTO permissions (id, code, name, description, module, scope, is_active, created_at, updated_at)
                VALUES (:id, :code, :name, :desc, :mod, :scope, :is_active, :now, :now)
                ON CONFLICT (code) DO NOTHING
            """),
            {
                "id": pid,
                "code": code,
                "name": name,
                "desc": desc,
                "mod": mod,
                "scope": scope,
                "is_active": True,
                "now": now,
            },
        )

    admin_role = bind.execute(sa.text("SELECT id FROM roles WHERE code = 'admin'")).scalar()
    platform_admin = bind.execute(sa.text("SELECT id FROM roles WHERE code = 'platform_admin'")).scalar()
    p41 = bind.execute(sa.text("SELECT id FROM permissions WHERE code = 'ml_dashboard.read'")).scalar()
    p42 = bind.execute(sa.text("SELECT id FROM permissions WHERE code = 'ml_models.manage'")).scalar()
    if admin_role and p41:
        bind.execute(sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:rid, :pid) ON CONFLICT DO NOTHING"), {"rid": admin_role, "pid": p41})
    if admin_role and p42:
        bind.execute(sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:rid, :pid) ON CONFLICT DO NOTHING"), {"rid": admin_role, "pid": p42})
    if platform_admin and p42:
        bind.execute(sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:rid, :pid) ON CONFLICT DO NOTHING"), {"rid": platform_admin, "pid": p42})


    # Integración RS2: permisos vinculados al módulo que regula el acceso.
    bind = op.get_bind()
    if "module_permissions" in sa.inspect(bind).get_table_names():
        association = sa.table("module_permissions", sa.column("module_code", sa.String()), sa.column("permission_id", sa.Uuid()))
        permission = sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String()))
        for permission_code in ['ml_dashboard.read']:
            permission_id = bind.scalar(sa.select(permission.c.id).where(permission.c.code == permission_code))
            if permission_id is not None:
                bind.execute(association.insert().values(module_code='ml_analytics', permission_id=permission_id))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ('ml_dashboard.read', 'ml_models.manage'))"))
    bind.execute(sa.text("DELETE FROM permissions WHERE code IN ('ml_dashboard.read', 'ml_models.manage')"))
    op.drop_table("ml_anomalies")
    op.drop_table("ml_customer_segments")
    op.drop_table("ml_predictions")
    op.drop_table("ml_models")
    op.drop_table("ml_training_runs")
