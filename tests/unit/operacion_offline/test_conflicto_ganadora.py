from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select

from src.operacion_offline.infrastructure.models.sync import SyncConflictModel, SyncOperationModel
from src.ventas_pagos.application.stock_service import StockService
from src.ventas_pagos.infrastructure.models import StockModel


def test_dos_ventas_ultima_unidad_competing_operation_completa(saas_world):
    """Dos ventas sin conexión de la última unidad desde dos dispositivos → la segunda queda CONFLICT STOCK y competing_operation trae número, dispositivo, cajero, hora local y hora de sincronización de la primera."""
    w = saas_world
    headers = w.headers(w.admins[0])
    vid = w.variants[0].id
    branch_id = w.branches[0].id
    base_price_str = str(w.products[0].base_price)

    # Stock a 1
    stock_row = w.db.scalar(select(StockModel).where(StockModel.variant_id == vid, StockModel.branch_id == branch_id))
    stock_row.quantity = 1
    w.db.commit()

    # Venta 1
    crid_1 = uuid4()
    body_1 = {
        "device_id": "pos-device-alpha",
        "client_version": "1.0",
        "operations": [{
            "client_request_id": str(crid_1),
            "type": "SALE",
            "branch_id": str(branch_id),
            "device_id": "pos-device-alpha",
            "client_created_at": "2026-11-11T14:15:00Z",
            "payload": {
                "user_id": str(w.admins[0].id),
                "items": [{"variant_id": str(vid), "quantity": 1, "unit_price": base_price_str, "regular_price": base_price_str}],
                "subtotal": base_price_str,
                "total": base_price_str,
                "local_folio": "FOLIO-01",
            },
        }],
    }
    res_1 = w.client.post("/api/v1/sync/batch", headers=headers, json=body_1)
    assert res_1.status_code == 200
    r1 = res_1.json()["data"]["results"][0]
    assert r1["status"] == "CONFIRMED"
    num_1 = r1["server_number"]

    # Venta 2
    crid_2 = uuid4()
    body_2 = {
        "device_id": "pos-device-beta",
        "client_version": "1.0",
        "operations": [{
            "client_request_id": str(crid_2),
            "type": "SALE",
            "branch_id": str(branch_id),
            "device_id": "pos-device-beta",
            "client_created_at": "2026-11-11T14:18:00Z",
            "payload": {
                "user_id": str(w.admins[0].id),
                "items": [{"variant_id": str(vid), "quantity": 1, "unit_price": base_price_str, "regular_price": base_price_str}],
                "subtotal": base_price_str,
                "total": base_price_str,
                "local_folio": "FOLIO-02",
            },
        }],
    }
    res_2 = w.client.post("/api/v1/sync/batch", headers=headers, json=body_2)
    assert res_2.status_code == 200
    r2 = res_2.json()["data"]["results"][0]
    assert r2["status"] == "CONFLICT"
    conflict_id = r2["conflict_id"]

    c_det = w.client.get(f"/api/v1/sync/conflicts/{conflict_id}", headers=headers)
    assert c_det.status_code == 200
    comp = c_det.json()["data"]["competing_operation"]
    assert comp is not None
    assert comp["server_number"] == num_1
    assert comp["device_id"] == "pos-device-alpha"
    assert "synchronized_at" in comp


def test_venta_otra_prenda_no_desvia_competing_operation(saas_world):
    """Antes del conflicto se confirma otra venta de OTRA prenda en la misma sucursal → competing_operation sigue señalando la venta de la prenda en conflicto."""
    w = saas_world
    headers = w.headers(w.admins[0])
    vid_1 = w.variants[0].id
    branch_id = w.branches[0].id
    price_1_str = str(w.products[0].base_price)

    # Crear una segunda variante para esa sucursal
    from src.usuarios_catalogo.infrastructure.models.catalog import ProductVariantModel, SizeModel
    size_extra = SizeModel(tenant_id=w.tenants[0].id, code="L", name="Grande")
    w.db.add(size_extra)
    w.db.flush()
    var_2 = ProductVariantModel(
        product_id=w.products[0].id,
        size_id=size_extra.id,
        color_id=w.variants[0].color_id,
        sku="SKU-OTRA",
        is_active=True,
    )
    w.db.add(var_2)
    w.db.flush()
    w.db.add(StockModel(branch_id=branch_id, variant_id=var_2.id, quantity=10))

    # Stock de vid_1 a 1
    stock_row = w.db.scalar(select(StockModel).where(StockModel.variant_id == vid_1, StockModel.branch_id == branch_id))
    stock_row.quantity = 1
    w.db.commit()

    # Venta de vid_1
    crid_1 = uuid4()
    w.client.post("/api/v1/sync/batch", headers=headers, json={
        "device_id": "pos-alpha",
        "client_version": "1.0",
        "operations": [{
            "client_request_id": str(crid_1), "type": "SALE", "branch_id": str(branch_id), "device_id": "pos-alpha",
            "client_created_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"user_id": str(w.admins[0].id), "items": [{"variant_id": str(vid_1), "quantity": 1, "unit_price": price_1_str}], "subtotal": price_1_str, "total": price_1_str},
        }],
    })

    # Venta de var_2 (otra prenda) en la misma sucursal
    crid_otra = uuid4()
    w.client.post("/api/v1/sync/batch", headers=headers, json={
        "device_id": "pos-otra",
        "client_version": "1.0",
        "operations": [{
            "client_request_id": str(crid_otra), "type": "SALE", "branch_id": str(branch_id), "device_id": "pos-otra",
            "client_created_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"user_id": str(w.admins[0].id), "items": [{"variant_id": str(var_2.id), "quantity": 1, "unit_price": price_1_str}], "subtotal": price_1_str, "total": price_1_str},
        }],
    })

    # Segunda venta de vid_1 (conflicto)
    crid_2 = uuid4()
    res_2 = w.client.post("/api/v1/sync/batch", headers=headers, json={
        "device_id": "pos-beta",
        "client_version": "1.0",
        "operations": [{
            "client_request_id": str(crid_2), "type": "SALE", "branch_id": str(branch_id), "device_id": "pos-beta",
            "client_created_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"user_id": str(w.admins[0].id), "items": [{"variant_id": str(vid_1), "quantity": 1, "unit_price": price_1_str}], "subtotal": price_1_str, "total": price_1_str},
        }],
    })
    c_id = res_2.json()["data"]["results"][0]["conflict_id"]
    det = w.client.get(f"/api/v1/sync/conflicts/{c_id}", headers=headers).json()["data"]

    # Debe señalar a pos-alpha (venta de vid_1), NUNCA a pos-otra (venta de var_2)
    assert det["competing_operation"]["device_id"] == "pos-alpha"


def test_agotado_por_ajuste_inventario_competing_is_null(saas_world):
    """La unidad se agotó por un ajuste de inventario → competing_operation es null."""
    w = saas_world
    headers = w.headers(w.admins[0])
    vid = w.variants[0].id
    branch_id = w.branches[0].id
    price_str = str(w.products[0].base_price)

    # Agotar stock vía ajuste manual
    stock_svc = StockService(w.db, tenant_id=w.tenants[0].id)
    stock_svc.change(vid, branch_id, delta=-20, kind="adjustment", reason="Merma/Ajuste inventario", reference="ADJ-001")
    w.db.commit()

    # Venta offline entra en conflicto
    crid = uuid4()
    res = w.client.post("/api/v1/sync/batch", headers=headers, json={
        "device_id": "pos-adj-test",
        "client_version": "1.0",
        "operations": [{
            "client_request_id": str(crid), "type": "SALE", "branch_id": str(branch_id), "device_id": "pos-adj-test",
            "client_created_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"user_id": str(w.admins[0].id), "items": [{"variant_id": str(vid), "quantity": 1, "unit_price": price_str}], "subtotal": price_str, "total": price_str},
        }],
    })
    c_id = res.json()["data"]["results"][0]["conflict_id"]
    det = w.client.get(f"/api/v1/sync/conflicts/{c_id}", headers=headers).json()["data"]
    assert det["competing_operation"] is None


def test_retry_en_stock_sin_reponer_409_sigue_open(saas_world):
    """RETRY en STOCK sin reponer → 409 stock_still_insufficient y el conflicto sigue OPEN."""
    w = saas_world
    headers = w.headers(w.admins[0])
    vid = w.variants[0].id
    branch_id = w.branches[0].id
    price_str = str(w.products[0].base_price)

    # Agotar stock
    stock_row = w.db.scalar(select(StockModel).where(StockModel.variant_id == vid, StockModel.branch_id == branch_id))
    stock_row.quantity = 0
    w.db.commit()

    crid = uuid4()
    res = w.client.post("/api/v1/sync/batch", headers=headers, json={
        "device_id": "pos-retry-test",
        "client_version": "1.0",
        "operations": [{
            "client_request_id": str(crid), "type": "SALE", "branch_id": str(branch_id), "device_id": "pos-retry-test",
            "client_created_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"user_id": str(w.admins[0].id), "items": [{"variant_id": str(vid), "quantity": 1, "unit_price": price_str}], "subtotal": price_str, "total": price_str},
        }],
    })
    c_id = res.json()["data"]["results"][0]["conflict_id"]

    # Reintentar sin stock
    res_retry = w.client.post(
        f"/api/v1/sync/conflicts/{c_id}/resolve",
        headers=headers,
        json={"action": "RETRY", "note": "Reintento sin stock aún"},
    )
    assert res_retry.status_code == 409
    assert res_retry.json()["error"]["code"] == "stock_still_insufficient"

    # Conflicto debe seguir OPEN
    c_db = w.db.get(SyncConflictModel, UUID(str(c_id)))
    w.db.refresh(c_db)
    assert c_db.status == "OPEN"


def test_retry_en_stock_tras_ajustar_stock_resolved(saas_world):
    """RETRY en STOCK tras ajustar stock (+1) → conflicto RESOLVED, operación CONFIRMED y stock 0."""
    w = saas_world
    headers = w.headers(w.admins[0])
    vid = w.variants[0].id
    branch_id = w.branches[0].id
    price_str = str(w.products[0].base_price)

    stock_row = w.db.scalar(select(StockModel).where(StockModel.variant_id == vid, StockModel.branch_id == branch_id))
    stock_row.quantity = 0
    w.db.commit()

    crid = uuid4()
    res = w.client.post("/api/v1/sync/batch", headers=headers, json={
        "device_id": "pos-retry-ok",
        "client_version": "1.0",
        "operations": [{
            "client_request_id": str(crid), "type": "SALE", "branch_id": str(branch_id), "device_id": "pos-retry-ok",
            "client_created_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"user_id": str(w.admins[0].id), "items": [{"variant_id": str(vid), "quantity": 1, "unit_price": price_str}], "subtotal": price_str, "total": price_str},
        }],
    })
    c_id = res.json()["data"]["results"][0]["conflict_id"]

    # Reponer stock (+1)
    stock_row.quantity = 1
    w.db.commit()

    # Reintentar
    res_retry = w.client.post(
        f"/api/v1/sync/conflicts/{c_id}/resolve",
        headers=headers,
        json={"action": "RETRY", "note": "Ingresó mercadería: 1 unidad"},
    )
    assert res_retry.status_code == 200
    assert res_retry.json()["data"]["status"] == "RESOLVED"
    assert res_retry.json()["data"]["resolution"] == "RETRY"

    op = w.db.scalar(select(SyncOperationModel).where(SyncOperationModel.client_request_id == crid))
    assert op.status == "CONFIRMED"
    w.db.refresh(stock_row)
    assert stock_row.quantity == 0


def test_purchase_rechaza_authorize_price_y_retry_pero_admite_cancel(saas_world):
    """AUTHORIZE_PRICE y RETRY sobre una operación PURCHASE → 422 validation_error; CANCEL → RESOLVED sin reintegro."""
    w = saas_world
    headers_cli = w.headers(w.customers[0])
    headers_adm = w.headers(w.admins[0])
    vid = w.variants[0].id
    branch_id = w.branches[0].id

    stock_row = w.db.scalar(select(StockModel).where(StockModel.variant_id == vid, StockModel.branch_id == branch_id))
    stock_row.quantity = 0
    w.db.commit()

    crid = uuid4()
    res = w.client.post("/api/v1/sync/batch", headers=headers_cli, json={
        "device_id": "app-purchase-cli",
        "client_version": "1.0",
        "operations": [{
            "client_request_id": str(crid), "type": "PURCHASE", "branch_id": str(branch_id), "device_id": "app-purchase-cli",
            "client_created_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"items": [{"variant_id": str(vid), "quantity": 1, "unit_price": str(w.products[0].base_price)}], "payment_method": "manual"},
        }],
    })
    c_id = res.json()["data"]["results"][0]["conflict_id"]

    # AUTHORIZE_PRICE en PURCHASE -> 422
    r_auth = w.client.post(f"/api/v1/sync/conflicts/{c_id}/resolve", headers=headers_adm, json={"action": "AUTHORIZE_PRICE", "note": "No aplica"})
    assert r_auth.status_code == 422

    # RETRY en PURCHASE -> 422
    r_retry = w.client.post(f"/api/v1/sync/conflicts/{c_id}/resolve", headers=headers_adm, json={"action": "RETRY", "note": "No aplica"})
    assert r_retry.status_code == 422

    # CANCEL -> 200 RESOLVED sin reintegro
    r_cancel = w.client.post(f"/api/v1/sync/conflicts/{c_id}/resolve", headers=headers_adm, json={"action": "CANCEL", "note": "Cancelación solicitada"})
    assert r_cancel.status_code == 200
    assert r_cancel.json()["data"]["status"] == "RESOLVED"
    assert r_cancel.json()["data"]["refund"] is None


def test_encargado_empresa_b_consulta_conflicto_empresa_a_retorna_404(saas_world):
    """Encargado de la empresa B consulta el conflicto de A → 404."""
    w = saas_world
    headers_a = w.headers(w.admins[0])
    headers_b = w.headers(w.admins[1])
    vid = w.variants[0].id
    branch_id = w.branches[0].id
    price_str = str(w.products[0].base_price)

    stock_row = w.db.scalar(select(StockModel).where(StockModel.variant_id == vid, StockModel.branch_id == branch_id))
    stock_row.quantity = 0
    w.db.commit()

    crid = uuid4()
    res = w.client.post("/api/v1/sync/batch", headers=headers_a, json={
        "device_id": "pos-device-a",
        "client_version": "1.0",
        "operations": [{
            "client_request_id": str(crid), "type": "SALE", "branch_id": str(branch_id), "device_id": "pos-device-a",
            "client_created_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"user_id": str(w.admins[0].id), "items": [{"variant_id": str(vid), "quantity": 1, "unit_price": price_str}], "subtotal": price_str, "total": price_str},
        }],
    })
    c_id = res.json()["data"]["results"][0]["conflict_id"]

    res_b = w.client.get(f"/api/v1/sync/conflicts/{c_id}", headers=headers_b)
    assert res_b.status_code == 404
