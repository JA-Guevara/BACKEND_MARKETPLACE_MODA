"""Claves de API y webhooks salientes firmados con outbox (PX-2.1).

Revision ID: 20261120_0040
Revises: 20261115_0039
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "20261120_0040"
down_revision: str | None = "20261115_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_PERMISSIONS = [
    (
        "20000000-0000-0000-0000-000000000063",
        "integrations.read",
        "Consultar integraciones",
        "Ver claves de API, webhooks y entregas de la empresa",
        "integrations",
        "tenant",
    ),
    (
        "20000000-0000-0000-0000-000000000064",
        "integrations.write",
        "Gestionar integraciones",
        "Crear y revocar claves de API y configurar webhooks salientes",
        "integrations",
        "tenant",
    ),
]


def _table_exists(bind, table_name: str) -> bool:
    insp = sa.inspect(bind)
    return table_name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    now_utc = datetime.now(timezone.utc)

    # 1. Tabla api_keys
    if not _table_exists(bind, "api_keys"):
        op.create_table(
            "api_keys",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("prefix", sa.String(length=16), nullable=False),
            sa.Column("key_hash", sa.String(length=128), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
        op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])

    # 2. Tabla webhook_endpoints
    if not _table_exists(bind, "webhook_endpoints"):
        op.create_table(
            "webhook_endpoints",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("url", sa.String(length=500), nullable=False),
            sa.Column("secret_enc", sa.LargeBinary(), nullable=False),
            sa.Column("events", sa.JSON(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_webhook_endpoints_tenant_id", "webhook_endpoints", ["tenant_id"])

    # 3. Tabla integration_events (outbox pattern)
    if not _table_exists(bind, "integration_events"):
        op.create_table(
            "integration_events",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_type", sa.String(length=100), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_integration_events_tenant_id", "integration_events", ["tenant_id"])
        op.create_index("ix_integration_events_created_at", "integration_events", ["created_at"])

    # 4. Tabla webhook_deliveries
    if not _table_exists(bind, "webhook_deliveries"):
        op.create_table(
            "webhook_deliveries",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("endpoint_id", sa.Uuid(), sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_id", sa.Uuid(), sa.ForeignKey("integration_events.id", ondelete="CASCADE"), nullable=False),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_webhook_deliveries_endpoint_id", "webhook_deliveries", ["endpoint_id"])
        op.create_index("ix_webhook_deliveries_event_id", "webhook_deliveries", ["event_id"])
        op.create_index("ix_webhook_deliveries_status", "webhook_deliveries", ["status"])

    # El módulo debe existir antes de sus FK y de sus permisos.
    if not bind.execute(sa.text("SELECT 1 FROM platform_modules WHERE code = 'integrations'")).scalar():
        bind.execute(sa.text("""INSERT INTO platform_modules
            (code,name,description,category,icon,kind,lifecycle,depends_on,web_routes,sort_order,created_at,updated_at)
            VALUES ('integrations','Integraciones','Claves de API y webhooks','Operación','↗','ADDON','GA','[]','[]',130,:now,:now)"""), {"now": now_utc})
    for plan_id in bind.execute(sa.text("SELECT id FROM plans WHERE upper(code) = 'PROFESIONAL'")).scalars():
        if not bind.execute(sa.text("SELECT 1 FROM plan_features WHERE plan_id=:id AND feature_code='integrations'"), {"id":plan_id}).scalar():
            bind.execute(sa.text("INSERT INTO plan_features (id,plan_id,feature_code,enabled,limit_value) VALUES (:id,:plan,'integrations',true,NULL)"), {"id":uuid.uuid4(),"plan":plan_id})

    # 5. Sembrar permisos 063 y 064
    for pid_str, code, name, desc, module_name, scope in NEW_PERMISSIONS:
        perm_uuid = uuid.UUID(pid_str)

        existing_by_code = bind.execute(
            sa.text("SELECT id FROM permissions WHERE code = :code"),
            {"code": code},
        ).scalar()

        if existing_by_code is None:
            existing_by_id = bind.execute(
                sa.text("SELECT code FROM permissions WHERE id = :id"),
                {"id": perm_uuid},
            ).scalar()
            if existing_by_id is not None:
                raise RuntimeError(
                    f"Conflicto de permisos: el id {pid_str} ya está ocupado por {existing_by_id} "
                    f"al intentar sembrar {code}."
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
            real_perm_id = perm_uuid
        else:
            real_perm_id = existing_by_code

        # Asociar a roles de empresa (admin)
        admin_roles = bind.execute(
            sa.text(
                "SELECT id FROM roles WHERE code IN ('admin', 'company_admin') "
                "AND is_active = true AND tenant_id IS NULL"
            )
        ).scalars().all()

        for role_id in admin_roles:
            already_assigned = bind.execute(
                sa.text(
                    "SELECT 1 FROM role_permissions WHERE role_id = :role_id AND permission_id = :perm_id"
                ),
                {"role_id": role_id, "perm_id": real_perm_id},
            ).scalar()
            if not already_assigned:
                bind.execute(
                    sa.text(
                        "INSERT INTO role_permissions (role_id, permission_id) VALUES (:role_id, :perm_id)"
                    ),
                    {"role_id": role_id, "perm_id": real_perm_id},
                )

        # Si existe tabla module_permissions, asociar permiso al módulo integrations
        if _table_exists(bind, "module_permissions"):
            mod_exists = bind.execute(
                sa.text("SELECT 1 FROM module_permissions WHERE module_code = :mod AND permission_id = :perm_id"),
                {"mod": module_name, "perm_id": real_perm_id},
            ).scalar()
            if not mod_exists:
                bind.execute(
                    sa.text(
                        "INSERT INTO module_permissions (module_code, permission_id) VALUES (:mod, :perm_id)"
                    ),
                    {"mod": module_name, "perm_id": real_perm_id},
                )


def downgrade() -> None:
    bind = op.get_bind()
    for pid_str, code, _, _, _, _ in NEW_PERMISSIONS:
        perm_uuid = uuid.UUID(pid_str)
        if _table_exists(bind, "module_permissions"):
            bind.execute(
                sa.text("DELETE FROM module_permissions WHERE permission_id = :id"),
                {"id": perm_uuid},
            )
        bind.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_id = :id"),
            {"id": perm_uuid},
        )
        bind.execute(
            sa.text("DELETE FROM permissions WHERE id = :id OR code = :code"),
            {"id": perm_uuid, "code": code},
        )

    bind.execute(sa.text("DELETE FROM plan_features WHERE feature_code='integrations'"))
    bind.execute(sa.text("DELETE FROM platform_modules WHERE code='integrations'"))

    if _table_exists(bind, "webhook_deliveries"):
        op.drop_table("webhook_deliveries")
    if _table_exists(bind, "integration_events"):
        op.drop_table("integration_events")
    if _table_exists(bind, "webhook_endpoints"):
        op.drop_table("webhook_endpoints")
    if _table_exists(bind, "api_keys"):
        op.drop_table("api_keys")
