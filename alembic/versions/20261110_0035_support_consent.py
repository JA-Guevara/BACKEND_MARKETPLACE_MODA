"""Soporte con consentimiento de la empresa (PX-0.2).

Revision ID: 20261110_0035
Revises: 20261110_0032
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "20261110_0035"
down_revision: str | None = "20261110_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_PERMISSIONS = [
    (
        "20000000-0000-0000-0000-000000000060",
        "support_access.approve",
        "Aprobar accesos de soporte",
        "Aprobar o rechazar solicitudes de acceso del equipo de soporte",
        "tenant",
        "tenant",
    ),
    (
        "20000000-0000-0000-0000-000000000061",
        "support.emergency",
        "Acceso de soporte de emergencia",
        "Iniciar sesión de soporte de emergencia sin aprobación previa",
        "platform",
        "platform",
    ),
]


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
    now_utc = datetime.now(timezone.utc)

    # 1. Modificar tabla tenants
    tenant_cols = _column_names(bind, "tenants")
    if "support_access_mode" not in tenant_cols:
        op.add_column(
            "tenants",
            sa.Column(
                "support_access_mode",
                sa.String(length=20),
                nullable=False,
                server_default="require_approval",
            ),
        )

    # 2. Modificar tabla support_sessions
    session_cols = _column_names(bind, "support_sessions")
    if "status" not in session_cols:
        op.add_column(
            "support_sessions",
            sa.Column(
                "status",
                sa.String(length=25),
                nullable=False,
                server_default="active",
            ),
        )
    if "approved_by_user_id" not in session_cols:
        op.add_column(
            "support_sessions",
            sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
        )
    if "approved_at" not in session_cols:
        op.add_column(
            "support_sessions",
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "decision_reason" not in session_cols:
        op.add_column(
            "support_sessions",
            sa.Column("decision_reason", sa.String(length=255), nullable=True),
        )
    if "request_expires_at" not in session_cols:
        op.add_column(
            "support_sessions",
            sa.Column("request_expires_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "is_emergency" not in session_cols:
        op.add_column(
            "support_sessions",
            sa.Column(
                "is_emergency",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    # 3. Sembrar permisos nuevos
    for pid_str, code, name, desc, module_name, scope in NEW_PERMISSIONS:
        perm_uuid = uuid.UUID(pid_str)

        existing_by_code = bind.execute(
            sa.text("SELECT id FROM permissions WHERE code = :code"),
            {"code": code},
        ).scalar()
        if existing_by_code:
            continue

        existing_by_id = bind.execute(
            sa.text("SELECT code FROM permissions WHERE id = :id"),
            {"id": perm_uuid},
        ).scalar()
        if existing_by_id and existing_by_id != code:
            raise RuntimeError(
                f"ID {pid_str} ocupado por otro código ({existing_by_id}). La migración falla por contrato."
            )

        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, name, description, module, scope, is_active, created_at, updated_at) "
                "VALUES (:id, :code, :name, :description, :module, :scope, :is_active, :now, :now)"
            ),
            {
                "id": perm_uuid,
                "code": code,
                "name": name,
                "description": desc,
                "module": module_name,
                "scope": scope,
                "is_active": True,
                "now": now_utc,
            },
        )

    # Asignar support_access.approve a roles de administrador de empresa
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r, permissions p "
            "WHERE r.code IN ('admin', 'superadmin') AND r.audience = 'TENANT' "
            "AND p.code = 'support_access.approve' "
            "AND NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
        )
    )

    # Asignar support.emergency a superadmin y platform_admin de plataforma
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r, permissions p "
            "WHERE r.code IN ('platform_admin', 'superadmin') AND r.audience = 'PLATFORM' "
            "AND p.code = 'support.emergency' "
            "AND NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    for pid_str, _, _, _, _, _ in NEW_PERMISSIONS:
        bind.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_id = :id"),
            {"id": uuid.UUID(pid_str)},
        )
        bind.execute(
            sa.text("DELETE FROM permissions WHERE id = :id"),
            {"id": uuid.UUID(pid_str)},
        )

    with op.batch_alter_table("support_sessions") as batch:
        batch.drop_column("is_emergency")
        batch.drop_column("request_expires_at")
        batch.drop_column("decision_reason")
        batch.drop_column("approved_at")
        batch.drop_column("approved_by_user_id")
        batch.drop_column("status")

    with op.batch_alter_table("tenants") as batch:
        batch.drop_column("support_access_mode")
