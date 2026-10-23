from sqlalchemy import select
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.inventario_sucursales.infrastructure.models.organization import BranchModel


def body(code="NUEVO", limit=3):
    return {"code": code, "name": "Plan Nuevo", "reference_price": "400.00", "duration_days": 30,
        "features": [{"feature_code": "products", "enabled": True}, {"feature_code": "max_active_branches", "limit_value": limit}]}


def test_planes_catalogo_codigo_y_limites(world):
    headers = world.headers(world.platform)
    listed = world.client.get("/api/v1/platform/plans", headers=headers).json()["data"]
    assert {plan["code"] for plan in listed} >= {"BASICO", "PROFESIONAL"}
    assert next(plan for plan in listed if plan["code"] == "BASICO")["tenants_count"] == 1
    catalog = world.client.get("/api/v1/platform/plans/features", headers=headers).json()["data"]
    assert len(catalog) == 8
    duplicate = world.client.post("/api/v1/platform/plans", headers=headers, json=body("BASICO"))
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "plan_code_taken"
    for value in (0, -1, None):
        response = world.client.post("/api/v1/platform/plans", headers=headers, json=body(limit=value))
        assert response.status_code == 422 and response.json()["error"]["code"] == "plan_limit_invalid"
    missing = body(); missing["features"] = []
    assert world.client.post("/api/v1/platform/plans", headers=headers, json=missing).json()["error"]["code"] == "plan_limit_invalid"
    assert world.client.post("/api/v1/platform/plans", headers=headers, json=body()).status_code == 201
    assert world.client.post("/api/v1/platform/plans", headers=world.headers(world.customers[0]), json=body()).status_code == 403
    assert world.client.patch(f"/api/v1/platform/plans/{world.plans[0].id}", headers=headers, json={"code": "CAMBIO"}).status_code == 422


def test_reducir_limite_notifica_excedidas_y_guarda_bitacora(world):
    tenant = world.tenants[1]
    for index in range(5):
        world.db.add(BranchModel(tenant_id=tenant.id, city_id=world.branches[1].city_id, code=f"EXTRA-{index}", name=f"Extra {index}", address="QA"))
    world.db.commit()
    response = world.client.patch(f"/api/v1/platform/plans/{world.plans[1].id}", headers=world.headers(world.platform), json={"features": body(limit=5)["features"]})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["exceeded_tenants"] == [tenant.trade_name]
    assert response.json()["data"]["plan"]["limits"]["max_active_branches"] == 5
    event = world.db.scalar(select(AuditEventModel).where(AuditEventModel.action == "plans.updated"))
    assert event.metadata_["before"]["limits"]["max_active_branches"] == 10
    assert event.metadata_["after"]["limits"]["max_active_branches"] == 5


def test_desactivar_conserva_suscripcion_y_no_ofrece_plan(world):
    headers = world.headers(world.platform)
    path = f"/api/v1/platform/plans/{world.plans[0].id}"
    assert world.client.post(path+"/deactivate", headers=headers).json()["data"]["is_active"] is False
    listed = world.client.get("/api/v1/platform/plans", headers=headers).json()["data"]
    assert "BASICO" not in {row["code"] for row in listed}
    detail = world.client.get("/api/v1/tenant/subscription", headers=world.headers(world.admins[0])).json()["data"]
    assert detail["current"]["plan_code"] == "BASICO"
    assert world.client.post(path+"/activate", headers=headers).json()["data"]["is_active"] is True
