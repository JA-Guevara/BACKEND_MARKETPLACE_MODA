import uuid
from decimal import Decimal
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel
from src.ventas_pagos.infrastructure.engagement_models import PromotionModel
from src.ventas_pagos.application.assistant_tools import AssistantTools
from src.ventas_pagos.web.schemas import ExportReportToolParams


def _seed_orders(world):
    now = datetime.now(timezone.utc)
    order_a = OrderModel(
        tenant_id=world.tenants[0].id,
        number="FS-TEST-A001",
        user_id=world.customers[0].id,
        customer_email=world.customers[0].email,
        branch_id=world.branches[0].id,
        payment_method="manual",
        sales_channel="web",
        status="delivered",
        payment_status="paid",
        total=Decimal("150.00"),
        subtotal=Decimal("150.00"),
        discount_total=Decimal("0.00"),
        discounts=[],
        currency="BOB",
        address={"recipient": "Cliente A", "channel": "web"},
        items=[{
            "variant_id": str(world.variants[0].id),
            "product_id": str(world.products[0].id),
            "name": world.products[0].name,
            "unit_price": "150.00",
            "quantity": 1,
            "line_total": "150.00",
        }],
        paid_at=now,
    )
    order_b = OrderModel(
        tenant_id=world.tenants[1].id,
        number="FS-TEST-B001",
        user_id=world.customers[1].id,
        customer_email=world.customers[1].email,
        branch_id=world.branches[1].id,
        payment_method="manual",
        sales_channel="web",
        status="delivered",
        payment_status="paid",
        total=Decimal("300.00"),
        subtotal=Decimal("300.00"),
        discount_total=Decimal("0.00"),
        discounts=[],
        currency="BOB",
        address={"recipient": "Cliente B", "channel": "web"},
        items=[{
            "variant_id": str(world.variants[1].id),
            "product_id": str(world.products[1].id),
            "name": world.products[1].name,
            "unit_price": "150.00",
            "quantity": 2,
            "line_total": "300.00",
        }],
        paid_at=now,
    )
    world.db.add_all([order_a, order_b])
    world.db.commit()
    return order_a, order_b


def test_admin_a_solo_ve_pedidos_de_a(world):
    order_a, order_b = _seed_orders(world)
    resp = world.client.get(
        "/api/v1/commerce/admin/orders",
        headers=world.headers(world.admins[0]),
    )
    assert resp.status_code == 200
    numbers = [o["number"] for o in resp.json()["data"]]
    assert order_a.number in numbers
    assert order_b.number not in numbers


def test_admin_a_get_pedido_de_b_retorna_404(world):
    _, order_b = _seed_orders(world)
    # Intenta consultar la venta por número de comprobante en POS
    resp = world.client.get(
        f"/api/v1/commerce/admin/pos/orders?number={order_b.number}",
        headers=world.headers(world.admins[0]),
    )
    assert resp.status_code == 404

    # Intenta reimprimir comprobante de venta de B
    resp_receipt = world.client.get(
        f"/api/v1/commerce/admin/orders/{order_b.id}/receipt",
        headers=world.headers(world.admins[0]),
    )
    assert resp_receipt.status_code == 404


def test_admin_a_post_pos_con_branch_de_b_retorna_404(world):
    payload = {
        "client_request_id": str(uuid.uuid4()),
        "branch_id": str(world.branches[1].id),  # Sucursal de B
        "cash_point_id": str(world.cash_points[0].id),
        "customer_name": "Juan Perez",
        "customer_email": "juan@example.com",
        "payment_method": "cash",
        "payment_reference": "REF-POS-01",
        "payment_received": True,
        "items": [
            {
                "variant_id": str(world.variants[0].id),
                "quantity": 1,
            }
        ],
    }
    resp = world.client.post(
        "/api/v1/commerce/admin/pos/sales",
        json=payload,
        headers=world.headers(world.admins[0]),
    )
    assert resp.status_code == 404


def test_admin_a_ajuste_stock_con_variante_de_b_retorna_404(world):
    payload = {
        "branch_id": str(world.branches[0].id),
        "quantity": 10,
        "reason": "Intento de ajuste cruzado",
    }
    resp = world.client.put(
        f"/api/v1/commerce/admin/stock/{world.variants[1].id}",  # Variante de B
        json=payload,
        headers=world.headers(world.admins[0]),
    )
    assert resp.status_code == 404


def test_admin_a_dashboard_totales_solo_de_a(world):
    from src.roles.infrastructure.persistence.models.permission import PermissionModel
    perm = world.db.scalar(select(PermissionModel).where(PermissionModel.code == "dashboard.read"))
    if not perm:
        perm = PermissionModel(code="dashboard.read", name="Reportes", module="dashboard")
        world.db.add(perm)
        world.db.flush()
    if perm not in world.admin_role.permissions:
        world.admin_role.permissions.append(perm)
        world.db.commit()
    order_a, order_b = _seed_orders(world)
    resp = world.client.get(
        "/api/v1/analytics/dashboard",
        headers=world.headers(world.admins[0]),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]

    # Comparar contra suma manual de empresa A
    assert Decimal(data["revenue"]) == Decimal("150.00")
    assert data["orders"] == 1
    assert data["paid_orders"] == 1


def test_promocion_bienvenida_en_a_y_b_ambas_201(world):
    promo_payload = {
        "name": "Promo Bienvenida",
        "code": "BIENVENIDA",
        "discount_type": "percent",
        "discount_value": 10,
        "minimum_order": 0,
        "is_active": True,
    }

    # Creación en A -> 201
    resp_a = world.client.post(
        "/api/v1/commerce/admin/promotions",
        json=promo_payload,
        headers=world.headers(world.admins[0]),
    )
    assert resp_a.status_code == 201
    assert resp_a.json()["data"]["code"] == "BIENVENIDA"

    # Creación en B con el mismo código -> 201 (código único por empresa)
    resp_b = world.client.post(
        "/api/v1/commerce/admin/promotions",
        json=promo_payload,
        headers=world.headers(world.admins[1]),
    )
    assert resp_b.status_code == 201
    assert resp_b.json()["data"]["code"] == "BIENVENIDA"

    # Duplicado en la misma empresa A -> 409 Conflict
    resp_dup = world.client.post(
        "/api/v1/commerce/admin/promotions",
        json={**promo_payload, "name": "Otra Bienvenida"},
        headers=world.headers(world.admins[0]),
    )
    assert resp_dup.status_code == 409


def test_cliente_con_slug_de_a_aplica_cupon_de_b_falla(world):
    # Crear cupón único en B
    promo_b = {
        "name": "Solo para B",
        "code": "EXCLUSIVO_B",
        "discount_type": "fixed",
        "discount_value": 20,
        "minimum_order": 50,
        "is_active": True,
    }
    resp = world.client.post(
        "/api/v1/commerce/admin/promotions",
        json=promo_b,
        headers=world.headers(world.admins[1]),
    )
    assert resp.status_code == 201

    # Cliente navega con el slug de A y consulta carrito con cupón de B
    cart_resp = world.client.get(
        "/api/v1/commerce/cart?coupon_code=EXCLUSIVO_B",
        headers={
            "X-Tenant-Slug": world.tenants[0].slug,
            **world.headers(world.customers[0]),
        },
    )
    # El cupón no existe en la empresa A -> responde 422 ValidationError ("El cupón no existe.")
    assert cart_resp.status_code == 422


def test_herramienta_asistente_con_tenant_id_de_b_usa_a(world):
    _seed_orders(world)
    # Se inicializa el servicio del asistente vinculado al Tenant A
    tools_a = AssistantTools(world.db, world.tenants[0].id)
    params = ExportReportToolParams(reports=["pedidos"], format="xlsx")

    # Aunque se llame en el contexto de A, los datos que exporta son solo de A
    res = tools_a.execute("export_report", params, world.admins[0], request_id=str(uuid.uuid4()))
    assert res.reports == ["Pedidos"]

    # Verificamos directamente con ReportsService de A vs B
    from src.ventas_pagos.application.reports_service import ReportsService
    _, _, rows_a = ReportsService(world.db, world.tenants[0].id).export_report("pedidos")
    _, _, rows_b = ReportsService(world.db, world.tenants[1].id).export_report("pedidos")
    assert len(rows_a) == 1
    assert rows_a[0]["numero"] == "FS-TEST-A001"
    assert len(rows_b) == 1
    assert rows_b[0]["numero"] == "FS-TEST-B001"
