"""Create authentication, users, roles, permissions and audit tables."""

import uuid
from datetime import datetime, timezone
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260903_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ROLE_IDS = {
    "superadmin": uuid.UUID("10000000-0000-0000-0000-000000000001"),
    "admin": uuid.UUID("10000000-0000-0000-0000-000000000002"),
    "store_manager": uuid.UUID("10000000-0000-0000-0000-000000000003"),
    "cashier": uuid.UUID("10000000-0000-0000-0000-000000000004"),
    "client": uuid.UUID("10000000-0000-0000-0000-000000000005"),
}
PERMISSION_IDS = {
    "users.read": uuid.UUID("20000000-0000-0000-0000-000000000001"),
    "users.write": uuid.UUID("20000000-0000-0000-0000-000000000002"),
    "roles.read": uuid.UUID("20000000-0000-0000-0000-000000000003"),
    "roles.write": uuid.UUID("20000000-0000-0000-0000-000000000004"),
    "audit.read": uuid.UUID("20000000-0000-0000-0000-000000000005"),
}


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(255)),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_permissions"),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
    )
    op.create_index("ix_permissions_code", "permissions", ["code"])
    op.create_index("ix_permissions_module", "permissions", ["module"])

    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255)),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
    )
    op.create_index("ix_roles_code", "roles", ["code"])

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(30)),
        sa.Column("document_number", sa.String(50)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("document_number", name="uq_users_document_number"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE", name="fk_role_permissions_role_id_roles"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE", name="fk_role_permissions_permission_id_permissions"),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permissions"),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_user_roles_user_id_users"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE", name="fk_user_roles_role_id_roles"),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("jti", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("replaced_by_jti", sa.String(64)),
        sa.Column("created_by_ip", sa.String(45)),
        sa.Column("revoked_by_ip", sa.String(45)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_refresh_tokens_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("jti", name="uq_refresh_tokens_jti"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_jti", "refresh_tokens", ["jti"])

    for table_name in ("password_reset_tokens", "email_verification_tokens"):
        op.create_table(
            table_name,
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name=f"fk_{table_name}_user_id_users"),
            sa.PrimaryKeyConstraint("id", name=f"pk_{table_name}"),
            sa.UniqueConstraint("token_hash", name=f"uq_{table_name}_token_hash"),
        )
        op.create_index(f"ix_{table_name}_user_id", table_name, ["user_id"])
        op.create_index(f"ix_{table_name}_token_hash", table_name, ["token_hash"])

    op.create_table(
        "user_addresses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(50), nullable=False),
        sa.Column("recipient_name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(30), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("address_line", sa.String(255), nullable=False),
        sa.Column("reference", sa.String(255)),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_user_addresses_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_user_addresses"),
    )
    op.create_index("ix_user_addresses_user_id", "user_addresses", ["user_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(100)),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL", name="fk_audit_events_actor_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    for column in ("actor_user_id", "action", "entity_type", "entity_id", "created_at"):
        op.create_index(f"ix_audit_events_{column}", "audit_events", [column])

    _seed_security_data()


def _seed_security_data() -> None:
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("module", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("is_system", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        permissions,
        [
            {"id": PERMISSION_IDS["users.read"], "code": "users.read", "name": "Consultar usuarios", "description": "Consultar usuarios y sus perfiles.", "module": "users", "is_active": True, "created_at": now, "updated_at": now},
            {"id": PERMISSION_IDS["users.write"], "code": "users.write", "name": "Gestionar usuarios", "description": "Crear, editar, activar y eliminar usuarios.", "module": "users", "is_active": True, "created_at": now, "updated_at": now},
            {"id": PERMISSION_IDS["roles.read"], "code": "roles.read", "name": "Consultar roles", "description": "Consultar roles y permisos.", "module": "roles", "is_active": True, "created_at": now, "updated_at": now},
            {"id": PERMISSION_IDS["roles.write"], "code": "roles.write", "name": "Gestionar roles", "description": "Crear y modificar roles y permisos.", "module": "roles", "is_active": True, "created_at": now, "updated_at": now},
            {"id": PERMISSION_IDS["audit.read"], "code": "audit.read", "name": "Consultar bitacora", "description": "Consultar eventos de auditoria.", "module": "audit", "is_active": True, "created_at": now, "updated_at": now},
        ],
    )
    op.bulk_insert(
        roles,
        [
            {"id": ROLE_IDS["superadmin"], "code": "superadmin", "name": "Superadministrador", "description": "Control completo de la plataforma.", "is_system": True, "is_active": True, "created_at": now, "updated_at": now},
            {"id": ROLE_IDS["admin"], "code": "admin", "name": "Administrador", "description": "Administracion general de la plataforma.", "is_system": True, "is_active": True, "created_at": now, "updated_at": now},
            {"id": ROLE_IDS["store_manager"], "code": "store_manager", "name": "Encargado de sucursal", "description": "Operacion de una sucursal.", "is_system": True, "is_active": True, "created_at": now, "updated_at": now},
            {"id": ROLE_IDS["cashier"], "code": "cashier", "name": "Cajero", "description": "Ventas presenciales y caja.", "is_system": True, "is_active": True, "created_at": now, "updated_at": now},
            {"id": ROLE_IDS["client"], "code": "client", "name": "Cliente", "description": "Cliente de la tienda web y movil.", "is_system": True, "is_active": True, "created_at": now, "updated_at": now},
        ],
    )
    role_permissions = sa.table(
        "role_permissions", sa.column("role_id", sa.Uuid()), sa.column("permission_id", sa.Uuid())
    )
    op.bulk_insert(
        role_permissions,
        [
            {"role_id": role_id, "permission_id": permission_id}
            for role_id in (ROLE_IDS["superadmin"], ROLE_IDS["admin"])
            for permission_id in PERMISSION_IDS.values()
        ],
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("user_addresses")
    op.drop_table("email_verification_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("permissions")
