"""Historial de copias de plataforma y permisos de operación y portabilidad.

Revision ID: 20261110_0032
Revises: 20261109_0031
"""
from datetime import datetime, timezone
from uuid import UUID

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20261110_0032"
down_revision = "20261109_0031"
branch_labels = None
depends_on = None

NEW_PERMISSIONS = (
    (UUID("20000000-0000-0000-0000-000000000057"), "platform.ops.read", "Consultar operación", "platform", "platform"),
    (UUID("20000000-0000-0000-0000-000000000058"), "platform.ops.write", "Gestionar operación", "platform", "platform"),
    (UUID("20000000-0000-0000-0000-000000000059"), "tenant.data_export", "Exportar datos de empresa", "users", "tenant"),
)

permissions = sa.table(
    "permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String()),
    sa.column("name"), sa.column("module"), sa.column("scope"), sa.column("is_active", sa.Boolean()),
    sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)),
)
roles = sa.table(
    "roles", sa.column("id", sa.Uuid()), sa.column("code"), sa.column("audience"),
    sa.column("tenant_id", sa.Uuid()), sa.column("is_system", sa.Boolean()),
)
role_permissions = sa.table("role_permissions", sa.column("role_id", sa.Uuid()), sa.column("permission_id", sa.Uuid()))
module_permissions = sa.table("module_permissions", sa.column("module_code"), sa.column("permission_id", sa.Uuid()))


def _preflight_permissions(bind) -> set[UUID]:
    existentes = set()
    for identifier, code, _, module, scope in NEW_PERMISSIONS:
        matches = bind.execute(
            sa.select(permissions.c.id, permissions.c.code, permissions.c.module, permissions.c.scope).where(
                sa.or_(permissions.c.id == identifier, permissions.c.code == code)
            )
        ).all()
        for match in matches:
            if match.id != identifier or match.code != code or match.scope != scope or match.module != module:
                raise RuntimeError(
                    f"Permiso reservado {code} ({identifier}) en conflicto con un permiso existente."
                )
            existentes.add(identifier)
    return existentes


def _rol_sistema(bind, code: str, audience: str) -> UUID:
    identifier = bind.scalar(sa.select(roles.c.id).where(
        roles.c.code == code, roles.c.audience == audience, roles.c.tenant_id.is_(None), roles.c.is_system.is_(True),
    ))
    if identifier is None:
        raise RuntimeError(f"Falta el rol de sistema {code} requerido por la revisión 0032.")
    return identifier


def _modulo_de_usuarios(bind) -> str | None:
    if not sa.inspect(bind).has_table("module_permissions"):
        return None
    modules = bind.scalars(sa.select(module_permissions.c.module_code).distinct().select_from(
        module_permissions.join(permissions, module_permissions.c.permission_id == permissions.c.id)
    ).where(permissions.c.code.in_(("users.read", "users.write")))).all()
    if len(modules) > 1:
        raise RuntimeError("Los permisos de usuarios no comparten un módulo para tenant.data_export.")
    return modules[0] if modules else None


def upgrade() -> None:
    bind = op.get_bind()
    existentes = _preflight_permissions(bind)
    admin = _rol_sistema(bind, "admin", "TENANT")
    platform = _rol_sistema(bind, "platform_admin", "PLATFORM")
    users_module = _modulo_de_usuarios(bind)

    op.create_table(
        "platform_backups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.CHAR(64)),
        sa.Column("storage_ref", sa.String(200)),
        sa.Column("alembic_revision", sa.String(40)),
        sa.Column("pg_server_version", sa.Integer()),
        sa.Column("verify_status", sa.String(10), nullable=False),
        sa.Column("verify_report", sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")),
        sa.Column("workflow_run_url", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("verify_status IN ('ok', 'failed', 'pending')", name=op.f("ck_platform_backups_verify_status")),
        sa.CheckConstraint(
            "verify_status <> 'ok' OR (sha256 IS NOT NULL AND size_bytes > 0 "
            "AND storage_ref IS NOT NULL AND alembic_revision IS NOT NULL "
            "AND pg_server_version IS NOT NULL AND pg_server_version > 0 AND verify_report IS NOT NULL)",
            name=op.f("ck_platform_backups_verified_artifact"),
        ),
        sa.UniqueConstraint("sha256", name="uq_platform_backups_sha256"),
    )
    op.create_index("ix_platform_backups_status_finished", "platform_backups", ["verify_status", sa.text("finished_at DESC")])
    op.create_index(
        "uq_platform_backups_failed_run", "platform_backups", ["workflow_run_url"], unique=True,
        postgresql_where=sa.text("sha256 IS NULL"), sqlite_where=sa.text("sha256 IS NULL"),
    )

    now = datetime.now(timezone.utc)
    for identifier, code, name, module, scope in NEW_PERMISSIONS:
        if identifier not in existentes:
            bind.execute(permissions.insert().values(
                id=identifier, code=code, name=name, module=module, scope=scope,
                is_active=True, created_at=now, updated_at=now,
            ))
        role_id = platform if scope == "platform" else admin
        assigned = bind.scalar(sa.select(role_permissions.c.role_id).where(
            role_permissions.c.role_id == role_id, role_permissions.c.permission_id == identifier,
        ))
        if assigned is None:
            bind.execute(role_permissions.insert().values(role_id=role_id, permission_id=identifier))
        if scope == "tenant" and users_module is not None:
            existing_module = bind.scalar(sa.select(module_permissions.c.module_code).where(
                module_permissions.c.permission_id == identifier,
            ))
            if existing_module is None:
                bind.execute(module_permissions.insert().values(module_code=users_module, permission_id=identifier))
            elif existing_module != users_module:
                raise RuntimeError("tenant.data_export ya está vinculado a otro módulo.")


def downgrade() -> None:
    bind = op.get_bind()
    has_module_permissions = sa.inspect(bind).has_table("module_permissions")
    for identifier, code, _, _, _ in NEW_PERMISSIONS:
        exact = sa.select(permissions.c.id).where(permissions.c.id == identifier, permissions.c.code == code)
        bind.execute(role_permissions.delete().where(role_permissions.c.permission_id.in_(exact)))
        if has_module_permissions:
            bind.execute(module_permissions.delete().where(module_permissions.c.permission_id.in_(exact)))
        bind.execute(permissions.delete().where(permissions.c.id == identifier, permissions.c.code == code))
    op.drop_table("platform_backups")
