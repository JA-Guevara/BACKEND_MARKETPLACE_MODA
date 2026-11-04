import uuid
import pytest
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from tests.unit.plataforma_saas.conftest import create_world


@pytest.fixture
def world(monkeypatch):
    from src.auth.application.services.auth_email_service import AuthEmailService
    monkeypatch.setattr(AuthEmailService, "send_tenant_invitation", lambda *args: False)
    w = create_world()
    yield w
    w.client.close()
    w.db.close()
    w.engine.dispose()


def test_admin_a_get_audit_log_solo_eventos_de_a_incluyendo_soporte(world):
    tenant_a = world.tenants[0]
    tenant_b = world.tenants[1]

    # 1. Evento normal de empresa A
    RecordAuditEvent(world.db).execute(
        action="users.profile_updated",
        entity_type="user",
        entity_id=str(world.admins[0].id),
        description="Admin A actualizó perfil",
        actor_user_id=world.admins[0].id,
        tenant_id=tenant_a.id,
    )
    world.db.commit()

    # 2. Evento de soporte en empresa A
    # Iniciar sesión de soporte en A
    resp_sup = world.client.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/support-sessions",
        headers=world.headers(world.platform),
        json={"reason": "Mantenimiento preventivo en empresa A", "duration_minutes": 60},
    )
    assert resp_sup.status_code == 201
    support_token = resp_sup.json()["data"]["access_token"]
    sup_headers = {"Authorization": f"Bearer {support_token}"}

    # Acción realizada durante el soporte
    resp_action = world.client.post(
        "/api/v1/catalog/admin/sizes",
        headers=sup_headers,
        json={"code": "XL_SUP", "name": "Extra Large Soporte"},
    )
    assert resp_action.status_code == 201, resp_action.text

    # 3. Evento normal de empresa B
    RecordAuditEvent(world.db).execute(
        action="users.profile_updated",
        entity_type="user",
        entity_id=str(world.admins[1].id),
        description="Admin B actualizó perfil",
        actor_user_id=world.admins[1].id,
        tenant_id=tenant_b.id,
    )
    world.db.commit()

    # Admin A consulta bitácora
    resp = world.client.get("/api/v1/audit-log", headers=world.headers(world.admins[0]))
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]["items"]

    assert len(items) >= 2
    # Todos los eventos pertenecen a la empresa A
    for item in items:
        assert item["tenant_id"] == str(tenant_a.id)

    # El evento realizado bajo soporte tiene actor_is_support == True
    support_events = [it for it in items if it["actor_is_support"] is True]
    assert len(support_events) >= 1
    support_ev = support_events[0]
    assert support_ev["support_session_id"] is not None
    assert support_ev["support_reason"] == "Mantenimiento preventivo en empresa A"


def test_admin_b_no_ve_eventos_de_a(world):
    tenant_a = world.tenants[0]
    tenant_b = world.tenants[1]

    # Crear evento exclusivo de A
    RecordAuditEvent(world.db).execute(
        action="secret.action_a",
        entity_type="secret",
        entity_id=str(uuid.uuid4()),
        description="Acción privada de empresa A",
        actor_user_id=world.admins[0].id,
        tenant_id=tenant_a.id,
    )
    world.db.commit()

    # Admin B consulta bitácora
    resp = world.client.get("/api/v1/audit-log", headers=world.headers(world.admins[1]))
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]["items"]

    descriptions = [it["description"] for it in items]
    assert "Acción privada de empresa A" not in descriptions
    for item in items:
        assert item["tenant_id"] == str(tenant_b.id)


def test_admin_a_recursos_del_probador_de_prenda_de_b_retorna_404(world):
    # Prenda de empresa B
    prenda_b = world.products[1]

    # Admin A intenta ver los assets del vestidor de prenda_b
    resp = world.client.get(
        f"/api/v1/vestidor/admin/products/{prenda_b.id}/assets",
        headers=world.headers(world.admins[0]),
    )
    assert resp.status_code == 404
