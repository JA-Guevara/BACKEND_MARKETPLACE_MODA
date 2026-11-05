from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import select

from src.plataforma_saas.application.jobs.suscripciones import calcular_lifecycle_state
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel


def test_solo_lectura_bloquea_post_de_venta_con_403(world):
    """Prueba obligatoria: POST de venta -> 403 subscription_read_only."""
    tenant_a = world.tenants[0]
    admin_a = world.admins[0]

    # Poner suscripción de Empresa A en solo lectura
    sub = world.db.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.tenant_id == tenant_a.id,
            SubscriptionModel.closed_at.is_(None),
        )
    )
    sub.status = "VENCIDA"
    sub.end_date = date.today() - timedelta(days=5)
    sub.grace_until = datetime.now(timezone.utc) - timedelta(days=2)
    sub.read_only_since = datetime.now(timezone.utc) - timedelta(days=1)
    world.db.commit()

    assert calcular_lifecycle_state(sub) == "read_only"

    # Intentar crear un producto vía POST de empresa
    headers_a = world.headers(admin_a)
    product_payload = {
        "name": "Camisa Denim",
        "description": "Prenda de prueba",
        "base_price": 150.0,
        "category_id": str(uuid4()),
        "gender": "UNISEX",
    }
    resp = world.client.post("/api/v1/catalog/admin/products", headers=headers_a, json=product_payload)
    assert resp.status_code == 403, resp.text
    err = resp.json()["error"]
    assert err["code"] == "subscription_read_only"


def test_solo_lectura_permite_get_y_exportacion(world):
    """Prueba obligatoria: GET y exportación permitidos en solo lectura."""
    tenant_a = world.tenants[0]
    admin_a = world.admins[0]

    # Poner suscripción de Empresa A en solo lectura
    sub = world.db.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.tenant_id == tenant_a.id,
            SubscriptionModel.closed_at.is_(None),
        )
    )
    sub.status = "VENCIDA"
    sub.end_date = date.today() - timedelta(days=5)
    sub.grace_until = datetime.now(timezone.utc) - timedelta(days=2)
    sub.read_only_since = datetime.now(timezone.utc) - timedelta(days=1)
    world.db.commit()

    headers_a = world.headers(admin_a)

    # 1. Consultar suscripción propia permitida
    resp_sub = world.client.get("/api/v1/tenant/subscription", headers=headers_a)
    assert resp_sub.status_code == 200, resp_sub.text
    data = resp_sub.json()["data"]["current"]
    assert data["lifecycle_state"] == "read_only"

    # 2. Consultar catálogo GET permitido
    resp_cat = world.client.get("/api/v1/catalog/admin/products", headers=headers_a)
    assert resp_cat.status_code == 200, resp_cat.text


def test_sync_batch_responde_rechazada_temporalmente_y_queda_pendiente(world):
    """Prueba obligatoria: /sync/batch en solo lectura responde rechazada temporalmente con motivo subscription_read_only."""
    tenant_a = world.tenants[0]
    admin_a = world.admins[0]

    # Poner suscripción de Empresa A en solo lectura
    sub = world.db.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.tenant_id == tenant_a.id,
            SubscriptionModel.closed_at.is_(None),
        )
    )
    sub.status = "VENCIDA"
    sub.end_date = date.today() - timedelta(days=5)
    sub.grace_until = datetime.now(timezone.utc) - timedelta(days=2)
    sub.read_only_since = datetime.now(timezone.utc) - timedelta(days=1)
    world.db.commit()

    headers_a = world.headers(admin_a)
    client_req_id = str(uuid4())
    branch = world.branches[0]

    batch_payload = {
        "device_id": "POS-TERMINAL-01",
        "client_version": "1.0.0",
        "operations": [
            {
                "client_request_id": client_req_id,
                "type": "SALE",
                "branch_id": str(branch.id),
                "device_id": "POS-TERMINAL-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {"total": "100.00", "lines": []},
            }
        ],
    }

    resp = world.client.post("/api/v1/sync/batch", headers=headers_a, json=batch_payload)
    assert resp.status_code == 200, resp.text
    results = resp.json()["data"]["results"]
    assert len(results) == 1
    assert results[0]["client_request_id"] == client_req_id
    assert results[0]["status"] in ("RETRY", "REJECTED")
    assert results[0]["reason_code"] == "subscription_read_only"
    assert "rechazada temporalmente" in results[0]["message"].lower()


def test_empresa_b_activa_no_se_ve_afectada(world):
    """Prueba obligatoria: Empresa B activa no se ve afectada por empresa A en solo lectura."""
    tenant_a = world.tenants[0]
    tenant_b = world.tenants[1]
    admin_b = world.admins[1]

    # Empresa A en solo lectura
    sub_a = world.db.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.tenant_id == tenant_a.id,
            SubscriptionModel.closed_at.is_(None),
        )
    )
    sub_a.status = "VENCIDA"
    sub_a.read_only_since = datetime.now(timezone.utc)
    world.db.commit()

    # Empresa B activa
    sub_b = world.db.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.tenant_id == tenant_b.id,
            SubscriptionModel.closed_at.is_(None),
        )
    )
    assert sub_b.status == "ACTIVA"
    assert sub_b.read_only_since is None
    assert calcular_lifecycle_state(sub_b) in ("active", "expiring")

    headers_b = world.headers(admin_b)
    resp_b = world.client.get("/api/v1/tenant/subscription", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json()["data"]["current"]["lifecycle_state"] in ("active", "expiring")
