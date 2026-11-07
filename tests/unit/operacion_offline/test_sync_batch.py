from datetime import datetime, timedelta, timezone
from uuid import uuid4
from decimal import Decimal

from sqlalchemy import select
from src.operacion_offline.infrastructure.models.sync import SyncBatchModel, SyncOperationModel
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel


def test_sync_batch_exitoso_y_replay_idempotente(saas_world):
    w = saas_world
    crid_sale = uuid4()
    crid_res = uuid4()

    sale_payload = {
        "user_id": str(w.admins[0].id),
        "items": [
            {
                "variant_id": str(w.variants[0].id),
                "quantity": 2,
                "unit_price": str(w.products[0].base_price),
                "regular_price": str(w.products[0].base_price),
            }
        ],
        "subtotal": str(w.products[0].base_price * 2),
        "total": str(w.products[0].base_price * 2),
        "payment_method": "cash",
        "local_folio": "OFF-001",
    }

    res_payload = {
        "branch_id": str(w.branches[0].id),
        "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        "items": [{"variant_id": str(w.variants[0].id), "quantity": 1}],
        "notes": "Prueba sync",
        "client_key": str(crid_res),
        "origin": "OFFLINE",
        "device_id": "test-device-01",
        "client_created_at": datetime.now(timezone.utc).isoformat(),
    }

    batch_body = {
        "device_id": "test-device-01",
        "client_version": "web-2026.11.06",
        "operations": [
            {
                "client_request_id": str(crid_sale),
                "type": "SALE",
                "branch_id": str(w.branches[0].id),
                "device_id": "test-device-01",
                "client_created_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                "payload": sale_payload,
            },
            {
                "client_request_id": str(crid_res),
                "type": "RESERVATION",
                "branch_id": str(w.branches[0].id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": res_payload,
            },
        ],
    }

    headers = w.headers(w.admins[0])
    headers["X-Request-ID"] = "f82ba1dd-3ee5-460b-8256-e04d8927c5f1"
    res = w.client.post("/api/v1/sync/batch", headers=headers, json=batch_body)
    assert res.headers["X-Request-ID"] == headers["X-Request-ID"]
    assert res.json()["data"]["request_id"] == headers["X-Request-ID"]
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert len(data["results"]) == 2
    assert data["results"][0]["status"] == "CONFIRMED"
    assert data["results"][1]["status"] == "CONFIRMED"
    assert data["results"][0]["replay"] is False

    # Stock descontado: 2 por venta + 1 por reserva = 3
    stock_qty = w.db.scalar(select(StockModel.quantity).where(StockModel.variant_id == w.variants[0].id))
    assert stock_qty == 17

    # Replay idéntico: no descuenta stock adicional y responde replay=True
    replay_res = w.client.post("/api/v1/sync/batch", headers=headers, json=batch_body)
    assert replay_res.status_code == 200
    replay_data = replay_res.json()["data"]
    assert replay_data["results"][0]["replay"] is True
    assert replay_data["results"][1]["replay"] is True
    assert replay_data["results"][0]["server_ref"] == data["results"][0]["server_ref"]

    stock_after = w.db.scalar(select(StockModel.quantity).where(StockModel.variant_id == w.variants[0].id))
    assert stock_after == 17


def test_sync_batch_uuid_reused_con_distinto_payload(saas_world):
    w = saas_world
    crid = uuid4()
    headers = w.headers(w.admins[0])

    op1 = {
        "device_id": "test-device-01",
        "client_version": "1.0",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "SALE",
                "branch_id": str(w.branches[0].id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "user_id": str(w.admins[0].id),
                    "items": [{"variant_id": str(w.variants[0].id), "quantity": 1}],
                    "subtotal": str(w.products[0].base_price),
                    "total": str(w.products[0].base_price),
                },
            }
        ],
    }
    r1 = w.client.post("/api/v1/sync/batch", headers=headers, json=op1)
    assert r1.status_code == 200
    assert r1.json()["data"]["results"][0]["status"] == "CONFIRMED"

    # Mismo client_request_id pero con total o items distintos
    op2 = {
        "device_id": "test-device-01",
        "client_version": "1.0",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "SALE",
                "branch_id": str(w.branches[0].id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "user_id": str(w.admins[0].id),
                    "items": [{"variant_id": str(w.variants[0].id), "quantity": 2}],
                    "subtotal": "200.00",
                    "total": "200.00",
                },
            }
        ],
    }
    r2 = w.client.post("/api/v1/sync/batch", headers=headers, json=op2)
    assert r2.status_code == 200
    assert r2.json()["data"]["results"][0]["status"] == "REJECTED"
    assert r2.json()["data"]["results"][0]["reason_code"] == "uuid_reused"


def test_sync_status_y_detalle_lotes(saas_world):
    w = saas_world
    headers = w.headers(w.admins[0])
    crid = uuid4()

    w.client.post(
        "/api/v1/sync/batch",
        headers=headers,
        json={
            "device_id": "test-device-01",
            "client_version": "1.0",
            "operations": [
                {
                    "client_request_id": str(crid),
                    "type": "SALE",
                    "branch_id": str(w.branches[0].id),
                    "device_id": "test-device-01",
                    "client_created_at": datetime.now(timezone.utc).isoformat(),
                    "payload": {
                        "user_id": str(w.admins[0].id),
                        "items": [{"variant_id": str(w.variants[0].id), "quantity": 1}],
                        "subtotal": str(w.products[0].base_price),
                        "total": str(w.products[0].base_price),
                    },
                }
            ],
        },
    )

    # Status check
    unknown_crid = uuid4()
    st = w.client.post(
        "/api/v1/sync/status",
        headers=headers,
        json={"client_request_ids": [str(crid), str(unknown_crid)]},
    )
    assert st.status_code == 200
    st_data = st.json()["data"]
    assert len(st_data) == 2
    assert st_data[0]["status"] == "CONFIRMED"
    assert st_data[1]["status"] == "UNKNOWN"

    # List batches
    batches_res = w.client.get("/api/v1/sync/batches", headers=headers)
    assert batches_res.status_code == 200
    batches_data = batches_res.json()["data"]
    assert batches_data["total"] >= 1
    batch_id = batches_data["items"][0]["id"]

    # Detail batch
    detail_res = w.client.get(f"/api/v1/sync/batches/{batch_id}", headers=headers)
    assert detail_res.status_code == 200
    assert len(detail_res.json()["data"]["operations"]) >= 1
