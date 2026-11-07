from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.inventario_sucursales.infrastructure.models.organization import BranchModel, UserBranchModel
from src.ventas_pagos.infrastructure.models import StockModel


@pytest.mark.parametrize("change", ["quantity", "total", "cash_point", "cash", "user", "payment"])
def test_offline_sale_rejects_invalid_data_without_changing_inventory(saas_world, change):
    w = saas_world
    payload = {
        "user_id": str(w.admin_a.id), "cash_point_id": str(w.cash_point_a.id),
        "items": [{"variant_id": str(w.variant_a.id), "quantity": 1, "unit_price": "150.00"}],
        "subtotal": "150.00", "total": "150.00", "cash_received": "150.00", "payment_method": "cash",
    }
    if change == "quantity":
        payload["items"][0]["quantity"] = -1
    elif change == "total":
        payload["total"] = "1.00"
    elif change == "cash_point":
        payload["cash_point_id"] = str(w.cash_point_b.id)
    elif change == "cash":
        payload["cash_received"] = "1.00"
    elif change == "user":
        payload["user_id"] = str(w.admin_b.id)
    else:
        payload["payment_method"] = "card"
    response = w.client.post("/api/v1/sync/batch", headers=w.headers(w.admin_a), json={
        "device_id": "qa-offline-device", "client_version": "qa",
        "operations": [{"client_request_id": str(uuid4()), "type": "SALE",
                        "branch_id": str(w.branch_a.id), "device_id": "qa-offline-device",
                        "client_created_at": datetime.now(timezone.utc).isoformat(), "payload": payload}],
    })
    assert response.status_code == 200, response.text
    assert response.json()["data"]["results"][0]["status"] == "REJECTED"
    assert w.db.scalar(select(StockModel.quantity).where(StockModel.variant_id == w.variant_a.id)) == 20


def test_snapshot_contains_only_authorized_staff_branches_and_cash_points(saas_world):
    w = saas_world
    staff = w.admin_a
    staff.roles = [w.store_manager_role]
    w.store_manager_role.permissions = [permission for permission in w.admin_role.permissions
                                        if permission.code in ("commerce.write", "sync.write", "reservations.write")]
    other = BranchModel(tenant_id=w.tenant_a.id, code="PRIVATE", name="Privada",
                        city_id=w.branch_a.city_id, address="Sucursal no asignada")
    w.db.add_all([other, UserBranchModel(tenant_id=w.tenant_a.id, user_id=staff.id,
                                       branch_id=w.branch_a.id, is_default=True)])
    w.db.commit()
    response = w.client.get("/api/v1/offline/snapshot", headers=w.headers(staff))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [branch["id"] for branch in data["branches"]] == [str(w.branch_a.id)]
    assert [cash["id"] for cash in data["cash_points"]] == [str(w.cash_point_a.id)]
    assert datetime.fromisoformat(data["price_valid_until"]) > datetime.now(timezone.utc)
    assert w.client.get("/api/v1/offline/snapshot", headers=w.headers(staff),
                        params={"branch_id": str(other.id)}).status_code == 404


def test_reservation_stock_conflict_is_resolvable_and_replay_does_not_duplicate(saas_world):
    w = saas_world
    stock = w.db.scalar(select(StockModel).where(StockModel.variant_id == w.variant_a.id))
    stock.quantity = 1
    w.db.commit()
    op_id = str(uuid4())
    body = {"device_id": "offline-qa-001", "client_version": "qa", "operations": [{
        "client_request_id": op_id, "type": "RESERVATION", "branch_id": str(w.branch_a.id),
        "device_id": "offline-qa-001", "client_created_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"branch_id": str(w.branch_a.id), "origin": "OFFLINE", "client_key": str(uuid4()),
                    "device_id": "offline-qa-001", "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                    "items": [{"variant_id": str(w.variant_a.id), "quantity": 2}]},
    }]}
    headers = w.headers(w.admin_a)
    result = w.client.post("/api/v1/sync/batch", headers=headers, json=body).json()["data"]["results"][0]
    assert result["status"] == "CONFLICT"
    conflict_id = result["conflict_id"]
    detail = w.client.get(f"/api/v1/sync/conflicts/{conflict_id}", headers=headers).json()["data"]
    assert detail["operation_type"] == "RESERVATION"
    assert detail["lines"][0]["requested_quantity"] == 2
    foreign = w.client.get(f"/api/v1/sync/conflicts/{conflict_id}", headers=w.headers(w.admin_b))
    assert foreign.status_code == 404
    resolved = w.client.post(f"/api/v1/sync/conflicts/{conflict_id}/resolve", headers=headers,
                            json={"action": "ADJUST", "quantities": {str(w.variant_a.id): 1}, "note": "Conservar una unidad"})
    assert resolved.status_code == 200, resolved.text
    replay = w.client.post("/api/v1/sync/batch", headers=headers, json=body).json()["data"]["results"][0]
    assert replay["status"] == "CONFIRMED" and replay["replay"]
    assert w.db.scalar(select(StockModel.quantity).where(StockModel.variant_id == w.variant_a.id)) == 0


def test_invalid_reservation_is_rejected_instead_of_retried_forever(saas_world):
    w = saas_world
    response = w.client.post("/api/v1/sync/batch", headers=w.headers(w.admin_a), json={
        "device_id": "offline-qa-001", "client_version": "qa", "operations": [{
            "client_request_id": str(uuid4()), "type": "RESERVATION", "branch_id": str(w.branch_a.id),
            "device_id": "offline-qa-001", "client_created_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"branch_id": str(w.branch_a.id), "items": []},
        }],
    })
    assert response.status_code == 200
    assert response.json()["data"]["results"][0]["status"] == "REJECTED"
