from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import select

from src.usuarios_catalogo.infrastructure.models.catalog import ProductModel, ProductVariantModel, SizeModel
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel, StockMovementModel


def test_exchanges_flujo_completo_y_movimientos_duales(saas_world):
    w = saas_world
    admin = w.admins[0]
    tenant = w.tenants[0]
    branch = w.branches[0]
    headers = w.headers(admin)

    # 1. Crear una segunda variante para hacer el cambio
    prod = w.products[0]
    size_l = SizeModel(tenant_id=tenant.id, code="L", name="Grande")
    w.db.add(size_l)
    w.db.flush()

    var_nueva = ProductVariantModel(
        product_id=prod.id,
        sku="SKU-REEMPLAZO-01",
        price_override=Decimal('180.00'),
        size_id=size_l.id,
        color_id=w.color.id,
        is_active=True,
    )
    w.db.add(var_nueva)
    w.db.flush()
    w.db.add(StockModel(branch_id=branch.id, variant_id=var_nueva.id, quantity=15))
    w.db.commit()

    var_original = w.variants[0]
    stock_orig_inicial = w.db.scalar(
        select(StockModel.quantity).where(
            StockModel.branch_id == branch.id, StockModel.variant_id == var_original.id
        )
    )
    assert stock_orig_inicial == 20

    # 2. Crear una orden pagada hace 3 días
    order_id = uuid4()
    order = OrderModel(
        id=order_id,
        tenant_id=tenant.id,
        branch_id=branch.id,
        number="ORD-EXCHANGE-001",
        user_id=w.customers[0].id,
        customer_email=w.customers[0].email,
        status="completed",
        payment_status="paid",
        payment_method="cash",
        total=Decimal("150.00"),
        subtotal=Decimal("150.00"),
        currency="BOB",
        address={"street": "Av. Principal 123"},
        paid_at=datetime.now(timezone.utc) - timedelta(days=3),
        items=[
            {
                "variant_id": str(var_original.id),
                "product_id": str(prod.id),
                "name": prod.name,
                "sku": var_original.sku,
                "unit_price": 150.00,
                "quantity": 1,
                "subtotal": 150.00,
            }
        ],
    )
    w.db.add(order)
    w.db.commit()

    # 3. Consultar y actualizar política de plazo
    r_pol = w.client.get("/api/v1/commerce/admin/exchanges/policy", headers=headers)
    assert r_pol.status_code == 200
    assert r_pol.json()["data"]["exchange_days"] == 15

    r_pol_up = w.client.put(
        "/api/v1/commerce/admin/exchanges/policy",
        json={"exchange_days": 30},
        headers=headers,
    )
    assert r_pol_up.status_code == 200
    assert r_pol_up.json()["data"]["exchange_days"] == 30

    # 4. Buscar orden para cambio
    r_lookup = w.client.get(
        f"/api/v1/commerce/admin/exchanges/lookup/{order.number}", headers=headers
    )
    assert r_lookup.status_code == 200
    lookup_data = r_lookup.json()["data"]
    assert lookup_data["order_number"] == "ORD-EXCHANGE-001"
    assert lookup_data["remaining_days"] >= 26
    assert lookup_data["can_exchange"] is True
    assert len(lookup_data["items"]) == 1
    assert lookup_data["items"][0]["available_for_exchange"] == 1

    # 5. Calcular cambio con prenda de mayor valor (cliente paga diferencia)
    calc_payload = {
        "branch_id": str(branch.id),
        "lines": [
            {
                "original_variant_id": str(var_original.id),
                "returned_quantity": 1,
                "original_unit_price": "150.00",
                "new_variant_id": str(var_nueva.id),
                "delivered_quantity": 1,
                "new_unit_price": "180.00",
            }
        ],
    }
    r_calc = w.client.post(
        "/api/v1/commerce/admin/exchanges/calculate",
        json=calc_payload,
        headers=headers,
    )
    assert r_calc.status_code == 200
    calc_data = r_calc.json()["data"]
    assert calc_data["difference_amount"] == "30.00"
    assert calc_data["tipo_diferencia"] == "PAGO_CLIENTE"

    # 6. Ejecutar cambio atómico
    crid = uuid4()
    exec_payload = {
        "original_order_id": str(order.id),
        "branch_id": str(branch.id),
        "payment_method": "cash",
        "cash_received": "30.00",
        "cash_returned": "0.00",
        "notes": "Cambio de talla y modelo en sucursal",
        "client_request_id": str(crid),
        "lines": calc_payload["lines"],
    }
    r_exec = w.client.post(
        "/api/v1/commerce/admin/exchanges",
        json=exec_payload,
        headers=headers,
    )
    assert r_exec.status_code == 201
    exec_data = r_exec.json()["data"]
    assert exec_data["status"] == "COMPLETED"
    assert exec_data["difference_amount"] == "30.00"
    assert len(exec_data["lines"]) == 1
    exchange_id = exec_data["id"]

    # 7. Verificar movimientos duales de stock
    # La variante devuelta debió aumentar de 20 a 21
    stock_orig_despues = w.db.scalar(
        select(StockModel.quantity).where(
            StockModel.branch_id == branch.id, StockModel.variant_id == var_original.id
        )
    )
    assert stock_orig_despues == 21

    # La variante entregada debió disminuir de 15 a 14
    stock_nueva_despues = w.db.scalar(
        select(StockModel.quantity).where(
            StockModel.branch_id == branch.id, StockModel.variant_id == var_nueva.id
        )
    )
    assert stock_nueva_despues == 14

    # Verificar bitácora de movimientos de inventario
    movs = w.db.scalars(
        select(StockMovementModel)
        .where(StockMovementModel.reference == exchange_id)
        .order_by(StockMovementModel.created_at.asc())
    ).all()
    assert len(movs) == 2
    assert {m.kind:m.delta for m in movs} == {'exchange_in':1,'exchange_out':-1}

    # 8. Reintento idempotente con mismo client_request_id
    r_replay = w.client.post(
        "/api/v1/commerce/admin/exchanges",
        json=exec_payload,
        headers=headers,
    )
    assert r_replay.status_code == 201 or r_replay.status_code == 200
    # El stock NO debe cambiar de nuevo
    assert w.db.scalar(
        select(StockModel.quantity).where(
            StockModel.branch_id == branch.id, StockModel.variant_id == var_original.id
        )
    ) == 21

    # 9. Listar y consultar detalle
    r_list = w.client.get("/api/v1/commerce/admin/exchanges", headers=headers)
    assert r_list.status_code == 200
    assert r_list.json()["data"]["total"] >= 1

    r_det = w.client.get(f"/api/v1/commerce/admin/exchanges/{exchange_id}", headers=headers)
    assert r_det.status_code == 200
    assert r_det.json()["data"]["original_order_number"] == "ORD-EXCHANGE-001"


def test_cambio_prenda_vencida_retorna_400(saas_world):
    w = saas_world
    headers = w.headers(w.admins[0])
    branch = w.branches[0]

    # Orden pagada hace 40 días con política de 15 días
    order = OrderModel(
        tenant_id=w.tenants[0].id,
        branch_id=branch.id,
        number="ORD-EXCHANGE-VENCIDA",
        user_id=w.customers[0].id,
        customer_email=w.customers[0].email,
        status="completed",
        payment_status="paid",
        payment_method="cash",
        total=Decimal("150.00"),
        subtotal=Decimal("150.00"),
        currency="BOB",
        address={"street": "Calle 1"},
        paid_at=datetime.now(timezone.utc) - timedelta(days=40),
        items=[
            {
                "variant_id": str(w.variants[0].id),
                "name": "Prenda",
                "unit_price": 150.00,
                "quantity": 1,
            }
        ],
    )
    w.db.add(order)
    w.db.commit()

    r = w.client.get(
        f"/api/v1/commerce/admin/exchanges/lookup/{order.number}", headers=headers
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "exchange_expired"
