from tests.unit.plataforma_saas.conftest import world
from src.integraciones.application.api_keys_service import ApiKeysService
from src.integraciones.application.webhooks_service import WebhooksService
from src.integraciones.infrastructure.models import IntegrationEventModel, WebhookEndpointModel
from sqlalchemy import select


def make_key(w, tenant_idx, scopes):
    return ApiKeysService(w.db).crear(w.tenants[tenant_idx].id, f"Sistema Prueba Tenant {tenant_idx}", scopes)


def test_catalogo_aislamiento_estricto_multitenant(world):
    """Verifica que el endpoint de catálogo solo devuelva las prendas de la empresa propietaria (RN03)."""
    _, raw_key_0 = make_key(world, 0, ["catalog:read"])
    _, raw_key_1 = make_key(world, 1, ["catalog:read"])

    # Empresa 0 consulta catálogo
    res0 = world.client.get("/api/v1/integrations/v1/catalog", headers={"X-API-Key": raw_key_0})
    assert res0.status_code == 200, res0.text
    data0 = res0.json()["data"]
    skus_0 = [var["sku"] for p in data0["items"] for var in p["variants"]]
    assert "SKU-0" in skus_0
    assert "SKU-1" not in skus_0

    # Empresa 1 consulta catálogo
    res1 = world.client.get("/api/v1/integrations/v1/catalog", headers={"X-API-Key": raw_key_1})
    assert res1.status_code == 200, res1.text
    data1 = res1.json()["data"]
    skus_1 = [var["sku"] for p in data1["items"] for var in p["variants"]]
    assert "SKU-1" in skus_1
    assert "SKU-0" not in skus_1


def test_catalogo_scope_insuficiente(world):
    """Verifica que una clave sin scope catalog:read sea rechazada con 403."""
    _, raw_key = make_key(world, 0, ["sales:read"])
    res = world.client.get("/api/v1/integrations/v1/catalog", headers={"X-API-Key": raw_key})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "api_key_scope"


def test_stock_adjust_actualizacion_y_aislamiento(world):
    """Verifica ajuste de inventario bidireccional desde un ERP externo y aislamiento por tenant."""
    _, raw_write_key = make_key(world, 0, ["stock:write", "stock:read"])
    _, raw_read_only_key = make_key(world, 0, ["stock:read"])

    # 1. Clave sin stock:write es rechazada con 403
    res_forbidden = world.client.post(
        "/api/v1/integrations/v1/stock/adjust",
        json={"items": [{"sku": "SKU-0", "branch_code": "CENTRAL", "quantity": 50, "mode": "set"}]},
        headers={"X-API-Key": raw_read_only_key},
    )
    assert res_forbidden.status_code == 403
    assert res_forbidden.json()["error"]["code"] == "api_key_scope"

    # 2. Ajuste exitoso con clave autorizada (mode 'set')
    res_ok = world.client.post(
        "/api/v1/integrations/v1/stock/adjust",
        json={"items": [{"sku": "SKU-0", "branch_code": "CENTRAL", "quantity": 42, "mode": "set"}]},
        headers={"X-API-Key": raw_write_key},
    )
    assert res_ok.status_code == 200, res_ok.text
    body = res_ok.json()["data"]
    assert body["updated_count"] == 1
    assert body["items"][0]["new_quantity"] == 42
    assert body["items"][0]["previous_quantity"] == 20

    # 3. Intentar ajustar una variante que pertenece a Empresa 1 (SKU-1) con la clave de Empresa 0 -> Rechazo 422
    res_cross_sku = world.client.post(
        "/api/v1/integrations/v1/stock/adjust",
        json={"items": [{"sku": "SKU-1", "branch_code": "CENTRAL", "quantity": 10, "mode": "set"}]},
        headers={"X-API-Key": raw_write_key},
    )
    assert res_cross_sku.status_code == 422
    assert "no pertenece a su empresa" in res_cross_sku.text

    # 4. Intentar ajustar una sucursal que pertenece a Empresa 1 (SUC-01) con la clave de Empresa 0 -> Rechazo 422
    res_cross_branch = world.client.post(
        "/api/v1/integrations/v1/stock/adjust",
        json={"items": [{"sku": "SKU-0", "branch_code": "SUC-01", "quantity": 10, "mode": "set"}]},
        headers={"X-API-Key": raw_write_key},
    )
    assert res_cross_branch.status_code == 422
    assert "no pertenece a su empresa" in res_cross_branch.text


def test_stock_adjust_dispara_webhook_stock_low(world):
    """Verifica que ajustar el stock a un valor crítico (<= 5) genere automáticamente el evento webhook 'stock.low'."""
    tenant = world.tenants[0]
    wh_svc = WebhooksService(world.db)
    ep, _ = wh_svc.crear_endpoint(
        tenant_id=tenant.id,
        url="https://api.erp-externo.com/webhooks/almacen",
        events=["stock.low", "stock.updated"],
    )

    _, raw_write_key = make_key(world, 0, ["stock:write"])

    # Ajustar stock a 3 unidades (crítico <= 5)
    res = world.client.post(
        "/api/v1/integrations/v1/stock/adjust",
        json={"items": [{"sku": "SKU-0", "branch_code": "CENTRAL", "quantity": 3, "mode": "set"}]},
        headers={"X-API-Key": raw_write_key},
    )
    assert res.status_code == 200, res.text

    # Verificar que se creó el evento stock.low para este tenant
    events = list(
        world.db.scalars(
            select(IntegrationEventModel).where(
                IntegrationEventModel.tenant_id == tenant.id,
                IntegrationEventModel.event_type == "stock.low",
            )
        ).all()
    )
    assert len(events) >= 1
    assert events[-1].payload["data"]["quantity"] == 3
    assert events[-1].payload["data"]["sku"] == "SKU-0"


def test_simulacion_webhook_firma_hmac(world):
    """Verifica el endpoint de simulación para verificar firmas HMAC y payloads de prueba."""
    headers = world.headers(world.admins[1])
    res = world.client.post(
        "/api/v1/tenant/integrations/webhooks/simulate",
        json={"event_type": "sale.confirmed", "data": {"order_id": "ORD-999", "total": "500.00"}},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["event_type"] == "sale.confirmed"
    assert data["signature_preview"] is not None
    assert len(data["signature_preview"]) == 64  # SHA256 hex
    assert "X-FS-Signature" in data["headers_example"]
    assert data["payload"]["data"]["order_id"] == "ORD-999"

