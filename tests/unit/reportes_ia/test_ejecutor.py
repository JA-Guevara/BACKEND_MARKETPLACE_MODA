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
