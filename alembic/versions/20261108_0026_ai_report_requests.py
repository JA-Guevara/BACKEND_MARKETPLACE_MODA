"""Reportes con IA y voz (CU-09).

Revision ID: 20261108_0026
Revises: 20261107_0025
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "20261108_0026"
down_revision: str | None = "20261107_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = [
    (
        "20000000-0000-0000-0000-000000000039",
        "ai_reports.use",
        "Generar reportes con IA",
        "Interpretar consultas en lenguaje natural y voz, y ejecutar reportes inteligentes",
        "ai_reports",
        "tenant",
    ),
    (
        "20000000-0000-0000-0000-000000000040",
        "ai_reports.history",
        "Consultar historial de reportes IA",
        "Ver consultas y reportes previamente ejecutados con IA",
        "ai_reports",
        "tenant",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    # 1. Crear tabla report_requests
    op.create_table(
        "report_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("interpreted_spec", sa.JSON(), nullable=False),
        sa.Column("execution_result", sa.JSON(), nullable=True),
        sa.Column("audio_duration_seconds", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="TEXT"),
        sa.Column("definition_code", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=True, server_default="EXECUTED"),
        sa.Column("export_format", sa.String(length=10), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("rows_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_report_requests_tenant_id",
        "report_requests",
        ["tenant_id"],
    )
    op.create_index(
        "ix_report_requests_created_at",
        "report_requests",
        ["created_at"],
    )

    # 2. Insertar permisos
    permissions_table = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("module", sa.String()),
        sa.column("scope", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    for pid, code, name, desc, mod, scope in NEW_PERMISSIONS:
        bind.execute(
            permissions_table.insert().values(
                id=uuid.UUID(pid),
                code=code,
                name=name,
                description=desc,
                module=mod,
                scope=scope,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )

    # Asociar permisos al rol admin del sistema
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Uuid()),
        sa.column("permission_id", sa.Uuid()),
    )
    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
    )
    admin_roles = bind.execute(
        sa.select(roles.c.id).where(roles.c.code == "admin")
    ).fetchall()
    for (rid,) in admin_roles:
        for pid, *_ in NEW_PERMISSIONS:
            bind.execute(
                role_permissions.insert().values(
                    role_id=rid,
                    permission_id=uuid.UUID(pid),
                )
            )


    # Integración RS2: permisos vinculados al módulo que regula el acceso.
    bind = op.get_bind()
    if "module_permissions" in sa.inspect(bind).get_table_names():
        association = sa.table("module_permissions", sa.column("module_code", sa.String()), sa.column("permission_id", sa.Uuid()))
        permission = sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String()))
        for permission_code in ['ai_reports.use', 'ai_reports.history']:
            permission_id = bind.scalar(sa.select(permission.c.id).where(permission.c.code == permission_code))
            if permission_id is not None:
                bind.execute(association.insert().values(module_code='ai_reports', permission_id=permission_id))


def downgrade() -> None:
    bind = op.get_bind()

    perm_ids = [uuid.UUID(pid) for pid, *_ in NEW_PERMISSIONS]
    op.execute(
        sa.delete(sa.table("role_permissions", sa.column("permission_id", sa.Uuid())))
        .where(sa.column("permission_id").in_(perm_ids))
    )
    op.execute(
        sa.delete(sa.table("permissions", sa.column("id", sa.Uuid())))
        .where(sa.column("id").in_(perm_ids))
    )

    op.drop_table("report_requests")
