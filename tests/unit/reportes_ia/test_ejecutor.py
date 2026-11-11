from datetime import date, datetime, timezone
from decimal import Decimal
import uuid
import pytest

from src.reportes_ia.application.ejecutor import Ejecutor
from src.reportes_ia.application.validador import SpecValidada
from src.reportes_ia.domain.especificacion import Dimension, Filters, Metric, Period, ReportSpec
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel


def test_ejecutor_aislamiento_multitenant_y_reportes(saas_world):
    w = saas_world
    tenant_a = w.tenants[0].id
    tenant_b = w.tenants[1].id
    branch_a = w.branches[0].id
    branch_b = w.branches[1].id

    # Sembrar pedidos para Tenant A
    order_a1 = OrderModel(
        tenant_id=tenant_a,
        branch_id=branch_a,
        number="ORD-A1",
        customer_email="a1@test.com",
        status="paid",
        payment_method="cash",
        total=Decimal("200.00"),
        subtotal=Decimal("200.00"),
        currency="BOB",
        address={},
        items=[
            {
                "product_name": "Vestido Lino",
                "quantity": 2,
                "unit_price": "100.00",
                "line_total": "200.00",
                "category_name": "Vestidos",
                "sku": "VES-LIN-M",
            }
        ],
        created_at=datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc),
    )
    order_a2 = OrderModel(
        tenant_id=tenant_a,
        branch_id=branch_a,
        number="ORD-A2",
        customer_email="a2@test.com",
        status="paid",
        payment_method="card",
        total=Decimal("150.00"),
        subtotal=Decimal("150.00"),
        currency="BOB",
        address={},
        items=[
            {
                "product_name": "Falda Seda",
                "quantity": 1,
                "unit_price": "150.00",
                "line_total": "150.00",
                "category_name": "Faldas",
                "sku": "FAL-SED-S",
            }
        ],
        created_at=datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc),
    )

    # Sembrar pedido para Tenant B (para verificar aislamiento)
    order_b1 = OrderModel(
        tenant_id=tenant_b,
        branch_id=branch_b,
        number="ORD-B1",
        customer_email="b1@test.com",
        status="paid",
        payment_method="cash",
        total=Decimal("999.00"),
        subtotal=Decimal("999.00"),
        currency="BOB",
        address={},
        items=[
            {
                "product_name": "Vestido B",
                "quantity": 3,
                "unit_price": "333.00",
                "line_total": "999.00",
                "category_name": "Vestidos B",
            }
        ],
        created_at=datetime(2026, 9, 15, 11, 0, tzinfo=timezone.utc),
    )
    w.db.add_all([order_a1, order_a2, order_b1])
    w.db.commit()

    ejecutor = Ejecutor(w.db)
    periodo_sep = Period(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30), label="Septiembre")

    # 1. Ventas por sucursal en Tenant A
    spec_vps = ReportSpec(
        definition_code="ventas_por_sucursal",
        metrics=[Metric.REVENUE, Metric.ORDERS],
        dimensions=[Dimension.BRANCH],
        filters=Filters(period=periodo_sep),
    )
    res_a = ejecutor.ejecutar(SpecValidada(spec=spec_vps, tenant_id=tenant_a))

    # Debe contener solo las ventas de Tenant A (200 + 150 = 350), NUNCA 999 de Tenant B
    assert len(res_a.rows) == 1
    assert res_a.totals["revenue"] == 350.0
    assert res_a.totals["orders"] == 2
    assert res_a.rows[0]["revenue"] == 350.0

    # 2. Top productos en Tenant A
    spec_top = ReportSpec(
        definition_code="top_productos",
        metrics=[Metric.UNITS, Metric.REVENUE],
        dimensions=[Dimension.PRODUCT],
        filters=Filters(period=periodo_sep),
        top_n=5,
    )
    res_top = ejecutor.ejecutar(SpecValidada(spec=spec_top, tenant_id=tenant_a))
    assert len(res_top.rows) == 2
    assert res_top.rows[0]["product"] == "Vestido Lino"
    assert res_top.rows[0]["units"] == 2

    # 3. Ingresos por categoría en Tenant A
    spec_cat = ReportSpec(
        definition_code="ingresos_por_categoria",
        metrics=[Metric.REVENUE],
        dimensions=[Dimension.CATEGORY],
        filters=Filters(period=periodo_sep),
    )
    res_cat = ejecutor.ejecutar(SpecValidada(spec=spec_cat, tenant_id=tenant_a))
    assert len(res_cat.rows) == 2
    cats = {r["category"]: r["revenue"] for r in res_cat.rows}
    assert cats["Vestidos"] == 200.0
    assert cats["Faldas"] == 150.0

    # 4. Ventas por semana en Tenant A
    spec_sem = ReportSpec(
        definition_code="ventas_por_semana",
        metrics=[Metric.REVENUE],
        dimensions=[Dimension.WEEK],
        filters=Filters(period=periodo_sep),
    )
    res_sem = ejecutor.ejecutar(SpecValidada(spec=spec_sem, tenant_id=tenant_a))
    assert len(res_sem.rows) >= 1
    assert res_sem.totals["revenue"] == 350.0


def test_ingresos_por_categoria_resuelve_desde_bd_sin_category_name(saas_world):
    w = saas_world
    tenant_a = w.tenants[0].id
    branch_a = w.branches[0].id
    variant_a = w.variants[0]  # Pertenece a categoría "Vestidos" en conftest

    order_real = OrderModel(
        tenant_id=tenant_a,
        branch_id=branch_a,
        number="ORD-REAL-CAT",
        customer_email="cat@test.com",
        status="paid",
        payment_method="cash",
        total=Decimal("300.00"),
        subtotal=Decimal("300.00"),
        currency="BOB",
        address={},
        # Ítem como lo genera create_order real: sin category_name
        items=[
            {
                "variant_id": str(variant_a.id),
                "product_id": str(variant_a.product_id),
                "name": "Vestido Real",
                "quantity": 2,
                "unit_price": "150.00",
                "line_total": "300.00",
                "sku": variant_a.sku,
            }
        ],
        created_at=datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc),
    )
    w.db.add(order_real)
    w.db.commit()

    ejecutor = Ejecutor(w.db)
    periodo_sep = Period(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30), label="Septiembre")
    spec_cat = ReportSpec(
        definition_code="ingresos_por_categoria",
        metrics=[Metric.REVENUE],
        dimensions=[Dimension.CATEGORY],
        filters=Filters(period=periodo_sep),
    )
    res_cat = ejecutor.ejecutar(SpecValidada(spec=spec_cat, tenant_id=tenant_a))
    # Debe resolver la categoría "Vestidos" mediante variant_id, NO caer en "General"
    assert any(r["category"] == "Vestidos" and r["revenue"] >= 300.0 for r in res_cat.rows)


def test_top_productos_por_sucursal_limita_por_sucursal(saas_world):
    """Verifica que al agrupar por sucursal, el top_n se aplica por cada sucursal."""
    w = saas_world
    tenant_a = w.tenants[0].id
    branch_1 = w.branches[0].id
    # Crear una segunda sucursal para tenant_a
    from src.inventario_sucursales.infrastructure.models.organization import BranchModel
    branch_2 = BranchModel(
        id=uuid.uuid4(),
        tenant_id=tenant_a,
        city_id=w.branches[0].city_id,
        name="Sucursal Norte",
        code="SUC-NORTE",
        address="Av. Norte 123",
        is_active=True,
    )
    w.db.add(branch_2)

    # En branch_1: 3 productos distintos (10, 8, 5 unidades)
    # En branch_2: 3 productos distintos (20, 15, 12 unidades)
    orders = [
        OrderModel(
            tenant_id=tenant_a,
            branch_id=branch_1,
            number="ORD-B1-P1",
            customer_email="c@test.com",
            status="paid",
            payment_method="cash",
            total=Decimal("100"),
            subtotal=Decimal("100"),
            currency="BOB",
            address={},
            items=[{"product_name": "Prod B1-A", "quantity": 10, "unit_price": "10"}],
            created_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
        ),
        OrderModel(
            tenant_id=tenant_a,
            branch_id=branch_1,
            number="ORD-B1-P2",
            customer_email="c@test.com",
            status="paid",
            payment_method="cash",
            total=Decimal("80"),
            subtotal=Decimal("80"),
            currency="BOB",
            address={},
            items=[{"product_name": "Prod B1-B", "quantity": 8, "unit_price": "10"}],
            created_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
        ),
        OrderModel(
            tenant_id=tenant_a,
            branch_id=branch_1,
            number="ORD-B1-P3",
            customer_email="c@test.com",
            status="paid",
            payment_method="cash",
            total=Decimal("50"),
            subtotal=Decimal("50"),
            currency="BOB",
            address={},
            items=[{"product_name": "Prod B1-C", "quantity": 5, "unit_price": "10"}],
            created_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
        ),
        OrderModel(
            tenant_id=tenant_a,
            branch_id=branch_2.id,
            number="ORD-B2-P1",
            customer_email="c@test.com",
            status="paid",
            payment_method="cash",
            total=Decimal("200"),
            subtotal=Decimal("200"),
            currency="BOB",
            address={},
            items=[{"product_name": "Prod B2-A", "quantity": 20, "unit_price": "10"}],
            created_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
        ),
        OrderModel(
            tenant_id=tenant_a,
            branch_id=branch_2.id,
            number="ORD-B2-P2",
            customer_email="c@test.com",
            status="paid",
            payment_method="cash",
            total=Decimal("150"),
            subtotal=Decimal("150"),
            currency="BOB",
            address={},
            items=[{"product_name": "Prod B2-B", "quantity": 15, "unit_price": "10"}],
            created_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
        ),
        OrderModel(
            tenant_id=tenant_a,
            branch_id=branch_2.id,
            number="ORD-B2-P3",
            customer_email="c@test.com",
            status="paid",
            payment_method="cash",
            total=Decimal("120"),
            subtotal=Decimal("120"),
            currency="BOB",
            address={},
            items=[{"product_name": "Prod B2-C", "quantity": 12, "unit_price": "10"}],
            created_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
        ),
    ]
    w.db.add_all(orders)
    w.db.commit()

    ejecutor = Ejecutor(w.db)
    spec_top = ReportSpec(
        definition_code="top_productos",
        metrics=[Metric.UNITS, Metric.REVENUE],
        dimensions=[Dimension.BRANCH, Dimension.PRODUCT],
        filters=Filters(period=Period(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30), label="Septiembre")),
        top_n=2,
    )
    res_top = ejecutor.ejecutar(SpecValidada(spec=spec_top, tenant_id=tenant_a))

    # Cada sucursal debe tener exactamente top 2 (total 4 filas), no que branch_2 se coma las 2 posiciones
    b1_rows = [r for r in res_top.rows if r["branch"] == w.branches[0].name]
    b2_rows = [r for r in res_top.rows if r["branch"] == "Sucursal Norte"]

    assert len(b1_rows) == 2
    assert b1_rows[0]["product"] == "Prod B1-A"
    assert b1_rows[1]["product"] == "Prod B1-B"

    assert len(b2_rows) == 2
    assert b2_rows[0]["product"] == "Prod B2-A"
    assert b2_rows[1]["product"] == "Prod B2-B"


