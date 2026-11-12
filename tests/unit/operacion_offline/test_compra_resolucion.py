from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.operacion_offline.infrastructure.models.sync import SyncConflictModel, SyncOperationModel
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel


def _crear_compra_en_conflicto(w, customer, variant, branch, requested_qty=2, client_price="150.00", payment_method="stripe"):
    crid = uuid4()
    headers = w.headers(customer)
    body = {
        "device_id": "test-device-01",
        "client_version": "web-offline-v3",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "PURCHASE",
                "branch_id": str(branch.id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "items": [
                        {
                            "variant_id": str(variant.id),
                            "quantity": requested_qty,
                            "unit_price": client_price,
                        }
                    ],
                    "payment_method": payment_method,
                    "customer_name": "Ana Rojas",
                    "channel": "web",
                },
            }
        ],
    }
    res = w.client.post("/api/v1/sync/batch", headers=headers, json=body)
    assert res.status_code == 200
    r0 = res.json()["data"]["results"][0]
    assert r0["status"] == "CONFLICT"
    return crid, r0["conflict_id"]


def test_resolver_accept_stock_con_disponibilidad(saas_world):
    w = saas_world
    # Hay 1 unidad disponible y se piden 2
    stock_row = w.db.scalar(
        select(StockModel).where(
            StockModel.variant_id == w.variant_a.id,
            StockModel.branch_id == w.branch_a.id,
        )
    )
    stock_row.quantity = 1
    w.db.commit()

    crid, conflict_id = _crear_compra_en_conflicto(w, w.customer_a, w.variant_a, w.branch_a, requested_qty=2)

    headers = w.headers(w.customer_a)
    resolve_res = w.client.post(
        f"/api/v1/sync/purchases/{crid}/resolve",
        headers=headers,
        json={"action": "ACCEPT"},
    )
    # Debe ser 200 CONFIRMED con 1 unidad
    assert resolve_res.status_code == 200, resolve_res.text
    data = resolve_res.json()["data"]
    assert data["status"] == "CONFIRMED"
    assert data["payment_required"] is True
    assert data["total"] == "150.00"

    # Conflicto cerrado
    conflict = w.db.get(SyncConflictModel, conflict_id)
    assert conflict.status == "RESOLVED"


def test_resolver_accept_stock_sin_ninguna_unidad_409(saas_world):
    w = saas_world
    stock_row = w.db.scalar(
        select(StockModel).where(
            StockModel.variant_id == w.variant_a.id,
            StockModel.branch_id == w.branch_a.id,
        )
    )
    stock_row.quantity = 1
    w.db.commit()

    crid, conflict_id = _crear_compra_en_conflicto(w, w.customer_a, w.variant_a, w.branch_a, requested_qty=2)

    # Ahora el stock cae a 0 antes de resolver
    stock_row.quantity = 0
    w.db.commit()

    headers = w.headers(w.customer_a)
    resolve_res = w.client.post(
        f"/api/v1/sync/purchases/{crid}/resolve",
        headers=headers,
        json={"action": "ACCEPT"},
    )
    assert resolve_res.status_code == 409
    assert resolve_res.json()["error"]["code"] == "stock_still_insufficient"

    conflict = w.db.get(SyncConflictModel, conflict_id)
    assert conflict.status == "OPEN"


def test_resolver_accept_price_confirmed_al_precio_vigente(saas_world):
    w = saas_world
    # Cliente mandó precio 100 pero vigente es 150
    crid, conflict_id = _crear_compra_en_conflicto(w, w.customer_a, w.variant_a, w.branch_a, requested_qty=1, client_price="100.00")

    headers = w.headers(w.customer_a)
    resolve_res = w.client.post(
        f"/api/v1/sync/purchases/{crid}/resolve",
        headers=headers,
        json={"action": "ACCEPT"},
    )
    assert resolve_res.status_code == 200
    data = resolve_res.json()["data"]
    assert data["status"] == "CONFIRMED"
    assert data["total"] == "150.00"


def test_resolver_cancel_rejected_cancelled_by_customer(saas_world):
    w = saas_world
    crid, conflict_id = _crear_compra_en_conflicto(w, w.customer_a, w.variant_a, w.branch_a, requested_qty=50)

    headers = w.headers(w.customer_a)
    resolve_res = w.client.post(
        f"/api/v1/sync/purchases/{crid}/resolve",
        headers=headers,
        json={"action": "CANCEL"},
    )
    assert resolve_res.status_code == 200
    data = resolve_res.json()["data"]
    assert data["status"] == "REJECTED"
    assert data["reason_code"] == "cancelled_by_customer"

    conflict = w.db.get(SyncConflictModel, conflict_id)
    assert conflict.status == "RESOLVED"

    # No se creó orden
    order = w.db.scalar(select(OrderModel).where(OrderModel.client_request_id == crid))
    assert order is None


def test_resolver_segundo_intento_conflict_already_resolved(saas_world):
    w = saas_world
    crid, _ = _crear_compra_en_conflicto(w, w.customer_a, w.variant_a, w.branch_a, requested_qty=50)

    headers = w.headers(w.customer_a)
    r1 = w.client.post(
        f"/api/v1/sync/purchases/{crid}/resolve",
        headers=headers,
        json={"action": "CANCEL"},
    )
    assert r1.status_code == 200

    r2 = w.client.post(
        f"/api/v1/sync/purchases/{crid}/resolve",
        headers=headers,
        json={"action": "CANCEL"},
    )
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "conflict_already_resolved"


def test_resolver_otro_cliente_o_tenant_404(saas_world):
    w = saas_world
    crid, _ = _crear_compra_en_conflicto(w, w.customer_a, w.variant_a, w.branch_a, requested_qty=50)

    # Cliente de otra empresa (customer_b)
    headers_b = w.headers(w.customer_b)
    res_b = w.client.post(
        f"/api/v1/sync/purchases/{crid}/resolve",
        headers=headers_b,
        json={"action": "CANCEL"},
    )
    assert res_b.status_code == 404

    # Otro usuario de la misma empresa (admin_a o cliente ajeno)
    headers_admin = w.headers(w.admin_a)
    res_admin = w.client.post(
        f"/api/v1/sync/purchases/{crid}/resolve",
        headers=headers_admin,
        json={"action": "CANCEL"},
    )
    # Solo el dueño de la compra puede resolver
    assert res_admin.status_code in (403, 404)


def test_resolver_client_request_id_de_sale_404(saas_world):
    w = saas_world
    # Venta de caja con conflicto
    crid_sale = uuid4()
    headers_admin = w.headers(w.admin_a)
    body = {
        "device_id": "test-device-01",
        "client_version": "1.0",
        "operations": [
            {
                "client_request_id": str(crid_sale),
                "type": "SALE",
                "branch_id": str(w.branch_a.id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "user_id": str(w.admin_a.id),
                    "items": [{"variant_id": str(w.variant_a.id), "quantity": 50, "unit_price": "150.00"}],
                    "subtotal": "7500.00",
                    "total": "7500.00",
                },
            }
        ],
    }
    w.client.post("/api/v1/sync/batch", headers=headers_admin, json=body)

    # El endpoint /sync/purchases/{crid}/resolve debe dar 404 porque no es una PURCHASE
    res = w.client.post(
        f"/api/v1/sync/purchases/{crid_sale}/resolve",
        headers=headers_admin,
        json={"action": "CANCEL"},
    )
    assert res.status_code == 404
