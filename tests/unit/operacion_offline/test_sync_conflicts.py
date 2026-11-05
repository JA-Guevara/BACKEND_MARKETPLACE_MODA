from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from src.operacion_offline.infrastructure.models.sync import SyncConflictModel, SyncOperationModel
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel


def test_sync_stock_conflict_and_resolution_adjust(saas_world):
    w = saas_world
    headers = w.headers(w.admins[0])
    crid = uuid4()
    vid = w.variants[0].id
    branch_id = w.branches[0].id

    # Pedir 50 unidades cuando hay 20
    body = {
        "device_id": "test-device-01",
        "client_version": "1.0",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "SALE",
                "branch_id": str(branch_id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "user_id": str(w.admins[0].id),
                    "items": [{"variant_id": str(vid), "quantity": 50, "unit_price": str(w.products[0].base_price), "regular_price": str(w.products[0].base_price)}],
                    "subtotal": str(w.products[0].base_price * 50),
                    "total": str(w.products[0].base_price * 50),
                    "local_folio": "OFF-CF-01",
                },
            }
        ],
    }

    res = w.client.post("/api/v1/sync/batch", headers=headers, json=body)
    assert res.status_code == 200
    r0 = res.json()["data"]["results"][0]
    assert r0["status"] == "CONFLICT"
    assert r0["conflict_type"] == "STOCK"
    conflict_id = r0["conflict_id"]
    assert conflict_id is not None

    # Listar conflictos
    c_list = w.client.get("/api/v1/sync/conflicts?status=OPEN", headers=headers)
    assert c_list.status_code == 200
    assert any(c["id"] == conflict_id for c in c_list.json()["data"]["items"])

    # Obtener detalle de conflicto
    c_det = w.client.get(f"/api/v1/sync/conflicts/{conflict_id}", headers=headers)
    assert c_det.status_code == 200
    assert len(c_det.json()["data"]["lines"]) == 1
    assert c_det.json()["data"]["lines"][0]["requested_quantity"] == 50
    assert c_det.json()["data"]["lines"][0]["available_quantity"] == 20

    # Resolver con ADJUST: ajustar a 15 unidades
    resolve_res = w.client.post(
        f"/api/v1/sync/conflicts/{conflict_id}/resolve",
        headers=headers,
        json={
            "action": "ADJUST",
            "quantities": {str(vid): 15},
            "note": "Ajustado a disponibilidad real del mostrador.",
        },
    )
    assert resolve_res.status_code == 200
    assert resolve_res.json()["data"]["status"] == "RESOLVED"
    assert resolve_res.json()["data"]["resolution"] == "ADJUST"

    # Verificar que la operación pasó a CONFIRMED y descontó 15 unidades
    op = w.db.scalar(select(SyncOperationModel).where(SyncOperationModel.client_request_id == crid))
    assert op.status == "CONFIRMED"
    stock_after = w.db.scalar(select(StockModel.quantity).where(StockModel.variant_id == vid))
    assert stock_after == 5


def test_sync_price_conflict_and_resolution_authorize(saas_world):
    w = saas_world
    headers = w.headers(w.admins[0])
    crid = uuid4()
    vid = w.variants[0].id
    branch_id = w.branches[0].id

    # Precio en cliente 50 vs precio servidor base 100
    body = {
        "device_id": "test-device-01",
        "client_version": "1.0",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "SALE",
                "branch_id": str(branch_id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "user_id": str(w.admins[0].id),
                    "items": [{"variant_id": str(vid), "quantity": 1, "unit_price": "50.00", "regular_price": "50.00"}],
                    "subtotal": "50.00",
                    "total": "50.00",
                    "local_folio": "OFF-PRICE-01",
                },
            }
        ],
    }

    res = w.client.post("/api/v1/sync/batch", headers=headers, json=body)
    assert res.status_code == 200
    r0 = res.json()["data"]["results"][0]
    assert r0["status"] == "CONFLICT"
    assert r0["conflict_type"] == "PRICE"
    conflict_id = r0["conflict_id"]

    # Resolver con AUTHORIZE_PRICE
    resolve_res = w.client.post(
        f"/api/v1/sync/conflicts/{conflict_id}/resolve",
        headers=headers,
        json={
            "action": "AUTHORIZE_PRICE",
            "note": "Precio de folleto offline respetado por encargado.",
        },
    )
    assert resolve_res.status_code == 200
    assert resolve_res.json()["data"]["status"] == "RESOLVED"
    assert resolve_res.json()["data"]["resolution"] == "AUTHORIZE_PRICE"

    # Verificar que la orden guardó price_authorized_by
    op = w.db.scalar(select(SyncOperationModel).where(SyncOperationModel.client_request_id == crid))
    order = w.db.get(OrderModel, op.server_ref)
    assert order.price_authorized_by == w.admins[0].id


def test_sync_conflict_cancel(saas_world):
    w = saas_world
    headers = w.headers(w.admins[0])
    crid = uuid4()
    vid = w.variants[0].id
    branch_id = w.branches[0].id

    # Stock insuficiente
    body = {
        "device_id": "test-device-01",
        "client_version": "1.0",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "SALE",
                "branch_id": str(branch_id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "user_id": str(w.admins[0].id),
                    "items": [{"variant_id": str(vid), "quantity": 999}],
                    "subtotal": "99900.00",
                    "total": "99900.00",
                },
            }
        ],
    }
    res = w.client.post("/api/v1/sync/batch", headers=headers, json=body)
    conflict_id = res.json()["data"]["results"][0]["conflict_id"]

    # Cancelar conflicto
    resolve_res = w.client.post(
        f"/api/v1/sync/conflicts/{conflict_id}/resolve",
        headers=headers,
        json={
            "action": "CANCEL",
            "note": "Cliente decidió no esperar y solicitó reembolso completo.",
        },
    )
    assert resolve_res.status_code == 200
    assert resolve_res.json()["data"]["status"] == "RESOLVED"

    op = w.db.scalar(select(SyncOperationModel).where(SyncOperationModel.client_request_id == crid))
    assert op.status == "REJECTED"
    assert op.reason_code == "cancelled_by_manager"
