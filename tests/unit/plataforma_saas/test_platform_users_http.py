from datetime import datetime, timedelta, timezone
from uuid import uuid4
from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.plataforma_saas.infrastructure.models.support_session import SupportSessionModel


def test_get_users_filtro_blocked(world):
    # Bloquear al cliente 0
    cliente = world.customers[0]
    c = world.db.get(UserModel, cliente.id)
    c.locked_until = datetime.now(timezone.utc) + timedelta(hours=2)
    world.db.commit()

    resp = world.client.get(
        "/api/v1/platform/users?status=blocked",
        headers=world.headers(world.platform),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] >= 1
    for u in data["items"]:
        assert u["locked_until"] is not None


def test_post_user_unlock(world):
    cliente = world.customers[0]
    c = world.db.get(UserModel, cliente.id)
    c.locked_until = datetime.now(timezone.utc) + timedelta(hours=2)
    c.failed_login_attempts = 5
    world.db.commit()

    resp = world.client.post(
        f"/api/v1/platform/users/{c.id}/unlock",
        headers=world.headers(world.platform),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["locked_until"] is None

    # Verificar en BD y en bitácora
    world.db.expire_all()
    c_updated = world.db.get(UserModel, c.id)
    assert c_updated.locked_until is None

    evento = (
        world.db.query(AuditEventModel)
        .filter(
            AuditEventModel.action == "platform.user_unlocked",
            AuditEventModel.entity_id == str(c.id),
        )
        .first()
    )
    assert evento is not None
    assert evento.tenant_id == c.tenant_id


def test_post_admins_invitar_201(world):
    payload = {
        "first_name": "Laura",
        "last_name": "Paz",
        "email": "laura.paz@example.com",
    }
    resp = world.client.post(
        "/api/v1/platform/admins",
        headers=world.headers(world.platform),
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["email"] == "laura.paz@example.com"
    assert data["tenant_id"] is None
    assert "Plataforma" in data["roles"] or "platform_admin" in data["roles"]


def test_desactivar_ultimo_super_admin_409(world):
    # world.platform es el único super admin activo
    resp = world.client.post(
        f"/api/v1/platform/admins/{world.platform.id}/deactivate",
        headers=world.headers(world.platform),
    )
    assert resp.status_code in (400, 409)


def test_get_platform_audit_filtros(world):
    tenant_b = world.tenants[1]

    # Crear evento normal de tenant B
    ev1 = AuditEventModel(
        tenant_id=tenant_b.id,
        action="tenant.test_event",
        entity_type="test",
        entity_id="1",
        description="Evento de prueba B",
    )
    # Crear sesión de soporte para tenant A y evento ligado a soporte
    sess = SupportSessionModel(
        id=uuid4(),
        tenant_id=world.tenants[0].id,
        platform_user_id=world.platform.id,
        reason="Sesión de prueba soporte",
        duration_minutes=30,
        started_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    world.db.add(sess)
    world.db.flush()

    ev_soporte = AuditEventModel(
        tenant_id=world.tenants[0].id,
        support_session_id=sess.id,
        action="support.action_test",
        entity_type="test",
        entity_id="2",
        description="Evento con soporte",
    )
    world.db.add_all([ev1, ev_soporte])
    world.db.commit()

    # 1. Filtro support_only=true
    resp_sop = world.client.get(
        "/api/v1/platform/audit?support_only=true",
        headers=world.headers(world.platform),
    )
    assert resp_sop.status_code == 200, resp_sop.text
    items_sop = resp_sop.json()["data"]["items"]
    assert len(items_sop) >= 1
    assert all(it["support_session_id"] is not None for it in items_sop)

    # 2. Filtro tenant_id = B
    resp_b = world.client.get(
        f"/api/v1/platform/audit?tenant_id={tenant_b.id}",
        headers=world.headers(world.platform),
    )
    assert resp_b.status_code == 200, resp_b.text
    items_b = resp_b.json()["data"]["items"]
    assert len(items_b) >= 1
    assert all(it["tenant_id"] == str(tenant_b.id) for it in items_b)
