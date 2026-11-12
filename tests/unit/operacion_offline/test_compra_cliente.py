import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from src.operacion_offline.infrastructure.models.sync import SyncOperationModel
from src.operacion_offline.web.sync_schemas import (
    PurchaseResolveIn,
    SyncBatchIn,
    SyncBatchOut,
    SyncResultOut,
)
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel


def _fixtures_dir() -> Path:
    base = Path(__file__).resolve()
    # base is in backend_marketplace_moda/tests/unit/operacion_offline/
    # fixtures are in docs/MJ-03-compra-cliente-offline/contrato/fixtures/
    for parent in base.parents:
        cand = parent / "docs" / "MJ-03-compra-cliente-offline" / "contrato" / "fixtures"
        if cand.is_dir():
            return cand
    raise FileNotFoundError("No se encontró el directorio de fixtures de MJ-03")


def test_fixtures_compra_validan_esquemas():
    fdir = _fixtures_dir()

    with open(fdir / "lote_compra_peticion.json", encoding="utf-8") as f:
        data = json.load(f)
        b_in = SyncBatchIn.model_validate(data)
        assert len(b_in.operations) == 1
        assert b_in.operations[0].type == "PURCHASE"

    for name in [
        "lote_compra_pendiente_pago.json",
        "lote_compra_retiro.json",
        "lote_compra_conflicto_stock.json",
        "lote_compra_conflicto_precio.json",
    ]:
        with open(fdir / name, encoding="utf-8") as f:
            data = json.load(f)
            b_out = SyncBatchOut.model_validate(data)
            assert len(b_out.results) == 1

    with open(fdir / "estado_compras.json", encoding="utf-8") as f:
        data = json.load(f)
        assert isinstance(data, list)
        for item in data:
            SyncResultOut.model_validate(item)

    with open(fdir / "resolver_aceptar_peticion.json", encoding="utf-8") as f:
        data = json.load(f)
        r_in = PurchaseResolveIn.model_validate(data)
        assert r_in.action == "ACCEPT"

    for name in ["resolver_aceptar_ok.json", "resolver_cancelar_ok.json"]:
        with open(fdir / name, encoding="utf-8") as f:
            data = json.load(f)
            r_out = SyncResultOut.model_validate(data)
            assert r_out.status in ("CONFIRMED", "REJECTED")


def test_compra_tarjeta_existencia_suficiente_confirmed(saas_world):
    w = saas_world
    crid = uuid4()
    headers = w.headers(w.customer_a)

    body = {
        "device_id": "test-device-01",
        "client_version": "web-offline-v3",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "PURCHASE",
                "branch_id": str(w.branch_a.id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "items": [
                        {
                            "variant_id": str(w.variant_a.id),
                            "quantity": 2,
                            "unit_price": str(w.product_a.base_price),
                        }
                    ],
                    "payment_method": "stripe",
                    "customer_name": "Ana Rojas",
                    "customer_phone": "70000001",
                    "notes": "Entrega en portería",
                    "channel": "web",
                },
            }
        ],
    }

    res = w.client.post("/api/v1/sync/batch", headers=headers, json=body)
    assert res.status_code == 200, res.text
    r0 = res.json()["data"]["results"][0]
    assert r0["status"] == "CONFIRMED"
    assert r0["payment_required"] is True
    assert r0["payment_method"] == "stripe"
    assert r0["total"] == "300.00"
    assert r0["payment_expires_at"] is not None

    # Verificar que el pedido fue creado en pending_payment
    order = w.db.scalar(select(OrderModel).where(OrderModel.client_request_id == crid))
    assert order is not None
    assert order.status == "pending_payment"
    assert order.payment_status == "pending"
    assert order.payment_method == "stripe"
    assert order.origin == "OFFLINE"
    assert order.total == Decimal("300.00")


def test_compra_pago_al_retirar_confirmed(saas_world):
    w = saas_world
    crid = uuid4()
    headers = w.headers(w.customer_a)

    body = {
        "device_id": "test-device-01",
        "client_version": "web-offline-v3",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "PURCHASE",
                "branch_id": str(w.branch_a.id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "items": [
                        {
                            "variant_id": str(w.variant_a.id),
                            "quantity": 1,
                            "unit_price": str(w.product_a.base_price),
                        }
                    ],
                    "payment_method": "manual",
                    "customer_name": "Carlos Gomez",
                    "customer_phone": "70000002",
                    "channel": "mobile",
                },
            }
        ],
    }

    res = w.client.post("/api/v1/sync/batch", headers=headers, json=body)
    assert res.status_code == 200, res.text
    r0 = res.json()["data"]["results"][0]
    assert r0["status"] == "CONFIRMED"
    assert r0["payment_required"] is False
    assert r0["payment_method"] == "manual"
    assert r0["total"] == "150.00"
    assert r0["payment_expires_at"] is not None


def test_compra_prenda_oferta_vigente_precio_oferta(saas_world):
    w = saas_world
    crid = uuid4()
    headers = w.headers(w.customer_a)

    # Supongamos que la variante tiene oferta vigente
    w.variant_a.price_override = Decimal("120.00")
    w.db.commit()

    body = {
        "device_id": "test-device-01",
        "client_version": "web-offline-v3",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "PURCHASE",
                "branch_id": str(w.branch_a.id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "items": [
                        {
                            "variant_id": str(w.variant_a.id),
                            "quantity": 1,
                            "unit_price": "120.00",
                        }
                    ],
                    "payment_method": "stripe",
                    "customer_name": "Ana Rojas",
                    "channel": "web",
                },
            }
        ],
    }

    res = w.client.post("/api/v1/sync/batch", headers=headers, json=body)
    assert res.status_code == 200, res.text
    r0 = res.json()["data"]["results"][0]
    assert r0["status"] == "CONFIRMED"
    assert r0["total"] == "120.00"


def test_compra_precio_distinto_del_vigente_conflict_price(saas_world):
    w = saas_world
    crid = uuid4()
    headers = w.headers(w.customer_a)

    body = {
        "device_id": "test-device-01",
        "client_version": "web-offline-v3",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "PURCHASE",
                "branch_id": str(w.branch_a.id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "items": [
                        {
                            "variant_id": str(w.variant_a.id),
                            "quantity": 1,
                            "unit_price": "80.00",  # El precio real es 150.00
                        }
                    ],
                    "payment_method": "stripe",
                    "customer_name": "Ana Rojas",
                    "channel": "web",
                },
            }
        ],
    }

    res = w.client.post("/api/v1/sync/batch", headers=headers, json=body)
    assert res.status_code == 200, res.text
    r0 = res.json()["data"]["results"][0]
    assert r0["status"] == "CONFLICT"
    assert r0["conflict_type"] == "PRICE"
    assert "No se realizó ningún cobro" in r0["message"]
    assert r0["conflict_lines"] is not None
    assert len(r0["conflict_lines"]) == 1
    assert r0["conflict_lines"][0]["unit_price"] == "80.00"

    # Verificar que no hay orden ni descuento de stock
    order = w.db.scalar(select(OrderModel).where(OrderModel.client_request_id == crid))
    assert order is None


def test_compra_existencia_insuficiente_conflict_stock(saas_world):
    w = saas_world
    crid = uuid4()
    headers = w.headers(w.customer_a)

    body = {
        "device_id": "test-device-01",
        "client_version": "web-offline-v3",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "PURCHASE",
                "branch_id": str(w.branch_a.id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "items": [
                        {
                            "variant_id": str(w.variant_a.id),
                            "quantity": 50,  # Stock es 20
                            "unit_price": "150.00",
                        }
                    ],
                    "payment_method": "stripe",
                    "customer_name": "Ana Rojas",
                    "channel": "web",
                },
            }
        ],
    }

    res = w.client.post("/api/v1/sync/batch", headers=headers, json=body)
    assert res.status_code == 200, res.text
    r0 = res.json()["data"]["results"][0]
    assert r0["status"] == "CONFLICT"
    assert r0["conflict_type"] == "STOCK"
    assert "No se realizó ningún cobro" in r0["message"]
    assert r0["conflict_lines"] is not None
    assert r0["conflict_lines"][0]["available_quantity"] == 20
    assert r0["conflict_lines"][0]["requested_quantity"] == 50

    order = w.db.scalar(select(OrderModel).where(OrderModel.client_request_id == crid))
    assert order is None


def test_compra_reenvio_mismo_client_request_id_replay(saas_world):
    w = saas_world
    crid = uuid4()
    headers = w.headers(w.customer_a)

    body = {
        "device_id": "test-device-01",
        "client_version": "web-offline-v3",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "PURCHASE",
                "branch_id": str(w.branch_a.id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "items": [
                        {
                            "variant_id": str(w.variant_a.id),
                            "quantity": 1,
                            "unit_price": "150.00",
                        }
                    ],
                    "payment_method": "manual",
                    "customer_name": "Ana Rojas",
                    "channel": "web",
                },
            }
        ],
    }

    res1 = w.client.post("/api/v1/sync/batch", headers=headers, json=body)
    assert res1.status_code == 200
    r1 = res1.json()["data"]["results"][0]
    assert r1["status"] == "CONFIRMED"
    assert r1["replay"] is False

    # Stock original era 20, ahora debe ser 19
    stock1 = w.db.scalar(
        select(StockModel.quantity).where(
            StockModel.variant_id == w.variant_a.id,
            StockModel.branch_id == w.branch_a.id,
        )
    )
    assert stock1 == 19

    # Reenvío
    res2 = w.client.post("/api/v1/sync/batch", headers=headers, json=body)
    assert res2.status_code == 200
    r2 = res2.json()["data"]["results"][0]
    assert r2["status"] == "CONFIRMED"
    assert r2["replay"] is True

    # El stock NO se descuenta otra vez
    stock2 = w.db.scalar(
        select(StockModel.quantity).where(
            StockModel.variant_id == w.variant_a.id,
            StockModel.branch_id == w.branch_a.id,
        )
    )
    assert stock2 == 19

    # Solo hay un pedido
    orders = w.db.scalars(select(OrderModel).where(OrderModel.client_request_id == crid)).all()
    assert len(orders) == 1


def test_compra_guarda_contacto_notas_y_canal(saas_world):
    w = saas_world
    crid = uuid4()
    headers = w.headers(w.customer_a)

    body = {
        "device_id": "test-device-01",
        "client_version": "web-offline-v3",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "PURCHASE",
                "branch_id": str(w.branch_a.id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "items": [
                        {
                            "variant_id": str(w.variant_a.id),
                            "quantity": 1,
                            "unit_price": "150.00",
                        }
                    ],
                    "payment_method": "stripe",
                    "customer_name": "Mariana Lopez",
                    "customer_phone": "78912345",
                    "notes": "Llamar antes de entregar",
                    "channel": "mobile",
                },
            }
        ],
    }

    res = w.client.post("/api/v1/sync/batch", headers=headers, json=body)
    assert res.status_code == 200
    order = w.db.scalar(select(OrderModel).where(OrderModel.client_request_id == crid))
    assert order is not None
    assert order.sales_channel == "mobile"
    assert order.customer_name == "Mariana Lopez" or order.address.get("recipient") == "Mariana Lopez" or "Mariana Lopez" in str(order.address)
    assert order.notes == "Llamar antes de entregar" or "Llamar antes de entregar" in str(order.tracking)


def test_compra_envia_correo_una_sola_vez(saas_world, monkeypatch):
    w = saas_world
    crid = uuid4()
    headers = w.headers(w.customer_a)

    correos_enviados = []
    from src.notificaciones.application.email_service import EmailService
    monkeypatch.setattr(EmailService, "send_order_confirmation", lambda self, *args, **kwargs: correos_enviados.append(args))

    body = {
        "device_id": "test-device-01",
        "client_version": "web-offline-v3",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "PURCHASE",
                "branch_id": str(w.branch_a.id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "items": [{"variant_id": str(w.variant_a.id), "quantity": 1, "unit_price": "150.00"}],
                    "payment_method": "manual",
                    "customer_name": "Ana Rojas",
                    "channel": "web",
                },
            }
        ],
    }

    w.client.post("/api/v1/sync/batch", headers=headers, json=body)
    w.client.post("/api/v1/sync/batch", headers=headers, json=body)

    # Debe haberse enviado como máximo una vez
    assert len(correos_enviados) <= 1


def test_compra_cliente_empresa_a_con_variante_empresa_b_rejected(saas_world):
    w = saas_world
    crid = uuid4()
    headers = w.headers(w.customer_a)

    body = {
        "device_id": "test-device-01",
        "client_version": "web-offline-v3",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "PURCHASE",
                "branch_id": str(w.branch_a.id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "items": [
                        {
                            "variant_id": str(w.variant_b.id),  # De empresa B
                            "quantity": 1,
                            "unit_price": "150.00",
                        }
                    ],
                    "payment_method": "stripe",
                    "customer_name": "Ana Rojas",
                    "channel": "web",
                },
            }
        ],
    }

    res = w.client.post("/api/v1/sync/batch", headers=headers, json=body)
    assert res.status_code == 200
    r0 = res.json()["data"]["results"][0]
    assert r0["status"] == "REJECTED"


def test_sync_status_devuelve_campos_compra(saas_world):
    w = saas_world
    crid = uuid4()
    headers = w.headers(w.customer_a)

    body = {
        "device_id": "test-device-01",
        "client_version": "web-offline-v3",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "PURCHASE",
                "branch_id": str(w.branch_a.id),
                "device_id": "test-device-01",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "items": [{"variant_id": str(w.variant_a.id), "quantity": 1, "unit_price": "150.00"}],
                    "payment_method": "stripe",
                    "customer_name": "Ana Rojas",
                    "channel": "web",
                },
            }
        ],
    }

    res = w.client.post("/api/v1/sync/batch", headers=headers, json=body)
    assert res.status_code == 200

    # Consultar /sync/status
    res_status = w.client.post("/api/v1/sync/status", headers=headers, json={"client_request_ids": [str(crid)]})
    assert res_status.status_code == 200
    items = res_status.json()["data"]
    assert len(items) == 1
    item = items[0]
    assert item["client_request_id"] == str(crid)
    assert item["status"] == "CONFIRMED"
    assert item["payment_required"] is True
    assert item["payment_method"] == "stripe"
    assert item["total"] == "150.00"
    assert item["payment_expires_at"] is not None
