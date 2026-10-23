from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel


def url(world, index=0):
    return f"/api/v1/platform/tenants/{world.tenants[index].id}/subscription"


def test_detalle_cambio_plan_historial_y_evento(world):
    headers = world.headers(world.platform)
    detail = world.client.get(url(world), headers=headers).json()["data"]
    assert detail["usage"] == {"active_branches": 1, "max_active_branches": 2}
    assert detail["current"]["plan_code"] == "BASICO" and detail["history"] == []
    response = world.client.post(url(world)+"/change-plan", headers=headers, json={"plan_code": "PROFESIONAL", "reason": "Ampliar sucursales"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["current"]["plan_code"] == "PROFESIONAL" and len(data["history"]) == 1
    event = world.db.scalar(select(AuditEventModel).where(AuditEventModel.action == "subscriptions.plan_changed"))
    assert event.entity_type == "tenant" and event.entity_id == str(world.tenants[0].id)


def test_reducir_plan_rechaza_sin_cambios_y_exige_desactivar(world):
    for index in range(5):
        world.db.add(BranchModel(tenant_id=world.tenants[1].id, city_id=world.branches[1].city_id, code=f"EX-{index}", name=f"Extra {index}", address="QA"))
    world.db.commit()
    response = world.client.post(url(world, 1)+"/change-plan", headers=world.headers(world.platform), json={"plan_code": "BASICO", "reason": "Bajar plan"})
    assert response.status_code == 409 and response.json()["error"]["details"]["must_deactivate"] == 4
    subs = world.db.scalars(select(SubscriptionModel).where(SubscriptionModel.tenant_id == world.tenants[1].id)).all()
    assert len(subs) == 1 and subs[0].closed_at is None


def test_suspender_renovar_preserva_historial_y_duracion(world):
    headers = world.headers(world.platform)
    before = world.client.get(url(world), headers=headers).json()["data"]["current"]
    response = world.client.post(url(world)+"/status", headers=headers, json={"status": "SUSPENDIDA", "reason": "Pago pendiente"})
    assert response.status_code == 200, response.text
    own = world.client.get("/api/v1/tenant/subscription", headers=world.headers(world.admins[0])).json()["data"]
    assert own["current"]["status"] == "SUSPENDIDA" and len(own["history"]) == 1
    renewed = world.client.post(url(world)+"/renew", headers=headers, json={"reason": "Renovación mensual"})
    assert renewed.status_code == 200, renewed.text
    current = renewed.json()["data"]["current"]
    assert date.fromisoformat(current["start_date"]) == date.fromisoformat(before["end_date"])+timedelta(days=1)
    assert date.fromisoformat(current["end_date"]) == date.fromisoformat(before["end_date"])+timedelta(days=30)
    assert len(renewed.json()["data"]["history"]) == 2


def test_vencimiento_queda_guardado_otra_sesion(world):
    subscription = world.db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id == world.tenants[0].id))
    subscription.end_date = date.today()-timedelta(days=1)
    world.db.commit()
    response = world.client.get(url(world), headers=world.headers(world.platform))
    assert response.status_code == 200 and response.json()["data"]["current"]["status"] == "VENCIDA"
    with Session(world.engine) as separate:
        assert separate.get(SubscriptionModel, subscription.id).status == "VENCIDA"
    response = world.client.post(url(world)+"/status", headers=world.headers(world.platform), json={"status": "VENCIDA", "reason": "No permitido"})
    assert response.status_code == 422
