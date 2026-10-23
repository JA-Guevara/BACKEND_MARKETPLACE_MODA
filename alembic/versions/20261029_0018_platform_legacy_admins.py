"""Convierte administradores anteriores al SaaS en administradores de plataforma.

Solo afecta a cuentas de la empresa inicial que ya existían al crearla.
No convierte administradores nuevos ni modifica contraseñas o activaciones.
"""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from alembic import op
import sqlalchemy as sa

revision = "20261029_0018"
down_revision = "20261028_0017"
branch_labels = None
depends_on = None
ACTION = "platform.legacy_admin_promoted"
INITIAL_TENANT = UUID("30000000-0000-0000-0000-000000000001")


def tables():
    users = sa.table("users", sa.column("id", sa.Uuid()), sa.column("tenant_id", sa.Uuid()),
                     sa.column("created_at", sa.DateTime(timezone=True)),
                     sa.column("updated_at", sa.DateTime(timezone=True)),
                     sa.column("deleted_at", sa.DateTime(timezone=True)))
    tenants = sa.table("tenants", sa.column("id", sa.Uuid()), sa.column("slug", sa.String()),
                       sa.column("created_at", sa.DateTime(timezone=True)))
    roles = sa.table("roles", sa.column("id", sa.Uuid()), sa.column("code", sa.String()),
                     sa.column("is_active", sa.Boolean()))
    links = sa.table("user_roles", sa.column("user_id", sa.Uuid()), sa.column("role_id", sa.Uuid()))
    refresh = sa.table("refresh_tokens", sa.column("user_id", sa.Uuid()),
                       sa.column("revoked_at", sa.DateTime(timezone=True)))
    audit = sa.table("audit_events", sa.column("id", sa.Uuid()),
                     sa.column("action", sa.String()), sa.column("entity_type", sa.String()),
                     sa.column("entity_id", sa.String()), sa.column("description", sa.Text()),
                     sa.column("metadata", sa.JSON()), sa.column("created_at", sa.DateTime(timezone=True)))
    return users, tenants, roles, links, refresh, audit


def upgrade():
    bind = op.get_bind()
    users, tenants, roles, links, refresh, audit = tables()
    platform_id = bind.scalar(sa.select(roles.c.id).where(roles.c.code == "platform_admin", roles.c.is_active.is_(True)))
    if platform_id is None:
        raise RuntimeError("Falta el rol activo platform_admin; no se modificaron cuentas.")
    legacy = bind.execute(sa.select(users.c.id, users.c.tenant_id).distinct().select_from(
        users.join(tenants, tenants.c.id == users.c.tenant_id)
        .join(links, links.c.user_id == users.c.id).join(roles, roles.c.id == links.c.role_id)
    ).where(tenants.c.id == INITIAL_TENANT, users.c.created_at <= tenants.c.created_at,
            users.c.deleted_at.is_(None), roles.c.code.in_(["superadmin", "admin"]))).all()
    now = datetime.now(timezone.utc)
    for user_id, tenant_id in legacy:
        old_roles = list(bind.scalars(sa.select(links.c.role_id).where(links.c.user_id == user_id)))
        bind.execute(users.update().where(users.c.id == user_id).values(tenant_id=None, updated_at=now))
        bind.execute(links.delete().where(links.c.user_id == user_id))
        bind.execute(links.insert().values(user_id=user_id, role_id=platform_id))
        bind.execute(refresh.update().where(refresh.c.user_id == user_id, refresh.c.revoked_at.is_(None)).values(revoked_at=now))
        bind.execute(audit.insert().values(id=uuid4(), action=ACTION, entity_type="user", entity_id=str(user_id),
            description="Administrador anterior al SaaS convertido a administrador de plataforma por migración autorizada.",
            metadata={"revision": revision, "previous_tenant_id": str(tenant_id),
                      "previous_role_ids": [str(role_id) for role_id in old_roles]}, created_at=now))
    print(f"Administradores anteriores convertidos a plataforma: {len(legacy)}", flush=True)


def downgrade():
    bind = op.get_bind()
    users, _, roles, links, refresh, audit = tables()
    platform_id = bind.scalar(sa.select(roles.c.id).where(roles.c.code == "platform_admin"))
    events = bind.execute(sa.select(audit.c.entity_id, audit.c.metadata).where(audit.c.action == ACTION)
                          .order_by(audit.c.created_at.desc())).all()
    now = datetime.now(timezone.utc)
    for entity_id, metadata in events:
        if metadata.get("revision") != revision:
            continue
        user_id = UUID(entity_id)
        user = bind.execute(sa.select(users.c.tenant_id).where(users.c.id == user_id)).first()
        current_roles = set(bind.scalars(sa.select(links.c.role_id).where(links.c.user_id == user_id)))
        # No sobrescribir una configuración de alcance/roles cambiada después.
        if user is None or user.tenant_id is not None or current_roles != {platform_id}:
            continue
        bind.execute(users.update().where(users.c.id == user_id).values(
            tenant_id=UUID(metadata["previous_tenant_id"]), updated_at=now))
        bind.execute(links.delete().where(links.c.user_id == user_id))
        for role_id in metadata["previous_role_ids"]:
            bind.execute(links.insert().values(user_id=user_id, role_id=UUID(role_id)))
        bind.execute(refresh.update().where(refresh.c.user_id == user_id, refresh.c.revoked_at.is_(None)).values(revoked_at=now))
        bind.execute(audit.insert().values(id=uuid4(), action="platform.legacy_admin_reverted", entity_type="user",
            entity_id=entity_id, description="Conversión de administrador revertida mediante downgrade.",
            metadata={"revision": revision}, created_at=now))
