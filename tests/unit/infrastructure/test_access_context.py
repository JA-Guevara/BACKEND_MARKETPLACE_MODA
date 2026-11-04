"""Pruebas de AccessContext, soporte RFC 8693 y autorización multi-tenant."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from src.auth.infrastructure.security.jwt_service import JWTService
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.access_context import AccessContext, get_access_context, tenant_scope_permissions
from src.infrastructure.security.authorization import require_access, require_permissions, require_platform_permissions
from src.infrastructure.security.tenancy import TenantContext, get_tenant_context
from src.plataforma_saas.infrastructure.models.support_session import SupportSessionModel
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from tests.unit.plataforma_saas.conftest import create_world


@pytest.fixture
def saas_world():
    world = create_world()
    # Asegurar que existan permisos con scope 'tenant' y 'platform'
    db = world.db
    p_cat = db.scalar(select(PermissionModel).where(PermissionModel.code == "catalog.read"))
    if p_cat:
        p_cat.scope = "tenant"
    p_ten = db.scalar(select(PermissionModel).where(PermissionModel.code == "tenants.read"))
    if p_ten:
        p_ten.scope = "platform"
    db.commit()
    return world


def test_token_normal_admin_empresa(saas_world):
    world = saas_world
    admin = world.admins[0]
    token, _ = JWTService().create_access_token(str(admin.id), str(admin.tenant_id))

    router = APIRouter()

    @router.get("/test/access")
    def endpoint(ctx: AccessContext = Depends(require_access("catalog.read"))):
        return {
            "user_id": str(ctx.user.id),
            "tenant_id": str(ctx.tenant_id),
            "support_session_id": str(ctx.support_session_id) if ctx.support_session_id else None,
            "is_support": ctx.is_support,
            "is_platform": ctx.is_platform,
            "permissions": sorted(list(ctx.permissions)),
        }

    world.app.include_router(router)
    client = TestClient(world.app)

    res = client.get("/test/access", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["user_id"] == str(admin.id)
    assert data["tenant_id"] == str(admin.tenant_id)
    assert data["support_session_id"] is None
    assert data["is_support"] is False
    assert data["is_platform"] is False
    assert "catalog.read" in data["permissions"]


def test_token_soporte_vigente(saas_world):
    world = saas_world
    platform = world.platform
    tenant_target = world.tenants[0]
    now = datetime.now(timezone.utc)

    # Crear sesión de soporte activa en base de datos
    session = SupportSessionModel(
        tenant_id=tenant_target.id,
        platform_user_id=platform.id,
        reason="Revisión de configuración por solicitud del cliente",
        duration_minutes=60,
        started_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(minutes=55),
        ended_at=None,
    )
    world.db.add(session)
    world.db.commit()

    token, _ = JWTService().create_support_token(
        user_id=str(platform.id),
        tenant_id=str(tenant_target.id),
        session_id=str(session.id),
        expires_at=session.expires_at,
    )

    router = APIRouter()

    @router.get("/test/support/access")
    def endpoint(
        ctx: AccessContext = Depends(get_access_context),
        tenant_ctx: TenantContext = Depends(get_tenant_context),
    ):
        return {
            "ctx_tenant_id": str(ctx.tenant_id),
            "ctx_session_id": str(ctx.support_session_id),
            "is_support": ctx.is_support,
            "is_platform": ctx.is_platform,
            "tenant_ctx_tid": str(tenant_ctx.tenant_id),
            "tenant_ctx_ssid": str(tenant_ctx.support_session_id),
            "permissions": sorted(list(ctx.permissions)),
        }

    world.app.include_router(router)
    client = TestClient(world.app)

    res = client.get("/test/support/access", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ctx_tenant_id"] == str(tenant_target.id)
    assert data["ctx_session_id"] == str(session.id)
    assert data["is_support"] is True
    assert data["is_platform"] is False
    assert data["tenant_ctx_tid"] == str(tenant_target.id)
    assert data["tenant_ctx_ssid"] == str(session.id)
    assert "catalog.read" in data["permissions"]


def test_token_soporte_sesion_terminada_401(saas_world):
    world = saas_world
    platform = world.platform
    tenant_target = world.tenants[0]
    now = datetime.now(timezone.utc)

    # Sesión ya finalizada manualmente
    session = SupportSessionModel(
        tenant_id=tenant_target.id,
        platform_user_id=platform.id,
        reason="Mantenimiento",
        duration_minutes=60,
        started_at=now - timedelta(minutes=30),
        expires_at=now + timedelta(minutes=30),
        ended_at=now - timedelta(minutes=5),
        end_reason="manual",
    )
    world.db.add(session)
    world.db.commit()

    token, _ = JWTService().create_support_token(
        user_id=str(platform.id),
        tenant_id=str(tenant_target.id),
        session_id=str(session.id),
        expires_at=session.expires_at,
    )

    router = APIRouter()

    @router.get("/test/support/expired")
    def endpoint(ctx: AccessContext = Depends(get_access_context)):
        return {"ok": True}

    world.app.include_router(router)
    client = TestClient(world.app)

    res = client.get("/test/support/expired", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "support_session_expired"


def test_token_soporte_sub_ajeno_401(saas_world):
    world = saas_world
    platform = world.platform
    admin = world.admins[0]
    tenant_target = world.tenants[0]
    now = datetime.now(timezone.utc)

    session = SupportSessionModel(
        tenant_id=tenant_target.id,
        platform_user_id=platform.id,
        reason="Prueba seguridad",
        duration_minutes=60,
        started_at=now,
        expires_at=now + timedelta(minutes=60),
    )
    world.db.add(session)
    world.db.commit()

    # Token emitido con un sub diferente al creador de la sesión
    token, _ = JWTService().create_support_token(
        user_id=str(admin.id),
        tenant_id=str(tenant_target.id),
        session_id=str(session.id),
        expires_at=session.expires_at,
    )

    router = APIRouter()

    @router.get("/test/support/impostor")
    def endpoint(ctx: AccessContext = Depends(get_access_context)):
        return {"ok": True}

    world.app.include_router(router)
    client = TestClient(world.app)

    res = client.get("/test/support/impostor", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "support_session_expired"


def test_ruta_require_platform_permissions_con_token_soporte_403(saas_world):
    world = saas_world
    platform = world.platform
    tenant_target = world.tenants[0]
    now = datetime.now(timezone.utc)

    session = SupportSessionModel(
        tenant_id=tenant_target.id,
        platform_user_id=platform.id,
        reason="Prueba scope",
        duration_minutes=60,
        started_at=now,
        expires_at=now + timedelta(minutes=60),
    )
    world.db.add(session)
    world.db.commit()

    token, _ = JWTService().create_support_token(
        user_id=str(platform.id),
        tenant_id=str(tenant_target.id),
        session_id=str(session.id),
        expires_at=session.expires_at,
    )

    router = APIRouter()

    @router.get("/test/platform/only")
    def endpoint(user=Depends(require_platform_permissions("tenants.read"))):
        return {"ok": True}

    world.app.include_router(router)
    client = TestClient(world.app)

    res = client.get("/test/platform/only", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "platform_scope_only"


def test_record_audit_event_en_soporte(saas_world):
    world = saas_world
    platform = world.platform
    tenant_target = world.tenants[0]
    now = datetime.now(timezone.utc)

    session = SupportSessionModel(
        tenant_id=tenant_target.id,
        platform_user_id=platform.id,
        reason="Auditoría soporte",
        duration_minutes=60,
        started_at=now,
        expires_at=now + timedelta(minutes=60),
    )
    world.db.add(session)
    world.db.commit()

    token, _ = JWTService().create_support_token(
        user_id=str(platform.id),
        tenant_id=str(tenant_target.id),
        session_id=str(session.id),
        expires_at=session.expires_at,
    )

    router = APIRouter()

    @router.post("/test/support/audit-action")
    def endpoint(
        ctx: AccessContext = Depends(get_access_context),
        db=Depends(get_db),
    ):
        event = RecordAuditEvent(db).execute(
            action="product.update",
            entity_type="product",
            entity_id=str(uuid4()),
            description="Cambio de precio realizado durante soporte",
        )
        return {"event_id": str(event.id)}

    world.app.include_router(router)
    client = TestClient(world.app)

    res = client.post("/test/support/audit-action", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    event_id = UUID(res.json()["event_id"])

    event = world.db.get(AuditEventModel, event_id)
    assert event is not None
    assert event.tenant_id == tenant_target.id
    assert event.support_session_id == session.id
    assert event.actor_user_id == platform.id
