from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import pytest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select

from src.auth.infrastructure.persistence.models.refresh_token import RefreshTokenModel
from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel

spec = importlib.util.spec_from_file_location("migration_0018", Path(__file__).resolve().parents[3] /
    "alembic/versions/20261029_0018_platform_legacy_admins.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def prepare(world):
    cutoff = datetime.now(timezone.utc) - timedelta(days=2)
    tenant = world.db.get(TenantModel, migration.INITIAL_TENANT)
    tenant.created_at = cutoff
    world.admins[0].tenant_id = tenant.id
    world.customers[0].tenant_id = tenant.id
    world.admins[0].created_at = cutoff - timedelta(days=1)
    # Administrador igualmente antiguo de otra empresa: nunca se convierte.
    world.admins[1].created_at = cutoff - timedelta(days=1)
    world.customers[0].created_at = cutoff - timedelta(days=1)
    new_admin = UserModel(tenant_id=tenant.id, email="admin-nuevo@example.com", first_name="Nuevo",
        last_name="Admin", password_hash=world.admins[0].password_hash, roles=[world.admin_role],
        is_verified=True, created_at=cutoff + timedelta(days=1))
    refresh = RefreshTokenModel(user_id=world.admins[0].id, jti="legacy-session", token_hash="a"*64,
        expires_at=datetime.now(timezone.utc)+timedelta(days=1))
    world.db.add_all([new_admin, refresh])
    world.db.commit()
    return new_admin.id, refresh.id


def run(world, direction):
    with Operations.context(MigrationContext.configure(world.db.connection())):
        getattr(migration, direction)()
    world.db.expire_all()


@pytest.mark.parametrize("legacy_role", ["admin", "superadmin"])
def test_promueve_solo_admin_anterior_y_conserva_password_y_otras_empresas(world, legacy_role):
    world.admin_role.code = legacy_role
    world.db.commit()
    new_id, refresh_id = prepare(world)
    password = world.admins[0].password_hash
    run(world, "upgrade")
    assert world.admins[0].tenant_id is None
    assert [role.code for role in world.admins[0].roles] == ["platform_admin"]
    assert world.admins[0].password_hash == password
    assert world.db.get(RefreshTokenModel, refresh_id).revoked_at is not None
    assert world.admins[1].tenant_id == world.tenants[1].id
    assert world.customers[0].tenant_id == migration.INITIAL_TENANT
    assert world.db.get(UserModel, new_id).tenant_id == migration.INITIAL_TENANT
    assert world.client.get("/api/v1/platform/tenants", headers=world.headers(world.admins[0])).status_code == 200
    assert world.client.get("/api/v1/platform/tenants", headers=world.headers(world.admins[1])).status_code == 403


def test_idempotencia_y_reversion_auditable(world):
    prepare(world)
    old_tenant = world.admins[0].tenant_id
    run(world, "upgrade")
    run(world, "upgrade")
    assert world.db.scalar(select(func.count()).select_from(AuditEventModel).where(
        AuditEventModel.action == migration.ACTION)) == 1
    run(world, "downgrade")
    assert world.admins[0].tenant_id == old_tenant
    assert [role.code for role in world.admins[0].roles] == ["admin"]


def test_sesion_anterior_pierde_alcance_y_usuario_eliminado_no_se_promueve(world):
    prepare(world)
    old_headers = world.headers(world.admins[0])
    run(world, "upgrade")
    assert world.client.get("/api/v1/auth/me", headers=old_headers).status_code == 401
    run(world, "downgrade")
    world.admins[0].deleted_at = datetime.now(timezone.utc)
    world.db.flush()
    run(world, "upgrade")
    assert world.admins[0].tenant_id == migration.INITIAL_TENANT
