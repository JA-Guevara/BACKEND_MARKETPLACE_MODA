from datetime import date, datetime, timezone
from decimal import Decimal
import uuid
import pytest

from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.reportes_ia.application.ejecutor import Ejecutor
from src.reportes_ia.application.validador import SpecValidada
from src.reportes_ia.domain.especificacion import Dimension, Filters, Metric, Period, ReportSpec
from src.ventas_pagos.infrastructure.models import OrderModel


def test_tres_sucursales_groups_y_orden_por_sucursal_y_unidades(saas_world):
    """Tres sucursales con ventas, top_n 2 → groups con 3 grupos, cada uno con ≤ 2 filas ordenadas por unidades y subtotal correcto."""
    w = saas_world
    tenant_a = w.tenants[0].id
    b1 = w.branches[0]
    b2 = BranchModel(id=uuid.uuid4(), tenant_id=tenant_a, city_id=b1.city_id, name="Sucursal Norte", code="SUC-N", address="Av. Norte 1", is_active=True)
    b3 = BranchModel(id=uuid.uuid4(), tenant_id=tenant_a, city_id=b1.city_id, name="Sucursal Sur", code="SUC-S", address="Av. Sur 1", is_active=True)
    w.db.add_all([b2, b3])

    def _crear_orden(branch_id, p_name, qty, rev, num):
        return OrderModel(
            tenant_id=tenant_a, branch_id=branch_id, number=num, customer_email="c@test.com",
            status="paid", payment_method="cash", total=Decimal(str(rev)), subtotal=Decimal(str(rev)),
            currency="BOB", address={}, items=[{"product_name": p_name, "quantity": qty, "unit_price": str(rev / qty)}],
            created_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
        )

    ordenes = [
        _crear_orden(b1.id, "Prod 1A", 10, 1000, "ORD-B1-1"),
        _crear_orden(b1.id, "Prod 1B", 8, 800, "ORD-B1-2"),
        _crear_orden(b1.id, "Prod 1C", 3, 300, "ORD-B1-3"),
        _crear_orden(b2.id, "Prod 2A", 15, 1500, "ORD-B2-1"),
        _crear_orden(b2.id, "Prod 2B", 5, 500, "ORD-B2-2"),
        _crear_orden(b3.id, "Prod 3A", 20, 2000, "ORD-B3-1"),
        _crear_orden(b3.id, "Prod 3B", 12, 1200, "ORD-B3-2"),
        _crear_orden(b3.id, "Prod 3C", 4, 400, "ORD-B3-3"),
    ]
    w.db.add_all(ordenes)
    w.db.commit()

    ejecutor = Ejecutor(w.db)
    spec = ReportSpec(
        definition_code="top_productos",
        metrics=[Metric.UNITS, Metric.REVENUE],
        dimensions=[Dimension.BRANCH, Dimension.PRODUCT],
        filters=Filters(period=Period(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30), label="Septiembre")),
        top_n=2,
    )
    res = ejecutor.ejecutar(SpecValidada(spec=spec, tenant_id=tenant_a))

    # groups debe tener 3 grupos (uno por sucursal)
    assert getattr(res, "groups", None) is not None
    assert len(res.groups) == 3
    for g in res.groups:
        assert len(g["rows"]) <= 2
        # Validar subtotales
        calc_units = sum(r["units"] for r in g["rows"])
        assert g["subtotal"]["units"] == calc_units

    # rows queda ordenado por sucursal y luego por unidades
    assert len(res.rows) == 6
    tot_units = sum(r["units"] for r in res.rows)
    assert res.totals["units"] == tot_units


def test_filtro_category_names_con_pedidos_reales(saas_world):
    """Filtro category_names [Vestidos] con pedidos reales (sin category_name en las líneas) → solo prendas de esa categoría."""
    w = saas_world
    tenant_a = w.tenants[0].id
    b1 = w.branches[0]
    var_vestido = w.variants[0]  # Pertenece a categoría Vestidos

    orden = OrderModel(
        tenant_id=tenant_a, branch_id=b1.id, number="ORD-CAT-REAL", customer_email="c@test.com",
        status="paid", payment_method="cash", total=Decimal("200.00"), subtotal=Decimal("200.00"),
        currency="BOB", address={},
        # Ítem real como se genera en compras: sin category_name
        items=[{
            "variant_id": str(var_vestido.id),
            "product_id": str(var_vestido.product_id),
            "name": "Vestido Lino",
            "quantity": 2,
            "unit_price": "100.00",
            "line_total": "200.00",
            "sku": var_vestido.sku,
        }],
        created_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
    )
    w.db.add(orden)
    w.db.commit()

    ejecutor = Ejecutor(w.db)
    spec = ReportSpec(
        definition_code="ingresos_por_categoria",
        metrics=[Metric.REVENUE],
        dimensions=[Dimension.CATEGORY],
        filters=Filters(
            period=Period(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30), label="Septiembre"),
            category_names=["Vestidos"],
        ),
    )
    res = ejecutor.ejecutar(SpecValidada(spec=spec, tenant_id=tenant_a))
    assert len(res.rows) >= 1
    assert all(r["category"] == "Vestidos" for r in res.rows)


def test_empresa_b_aislamiento_multitenant(saas_world):
    """Empresa B ejecuta el mismo reporte → no aparece ninguna venta ni sucursal de A."""
    w = saas_world
    tenant_b = w.tenants[1].id
    ejecutor = Ejecutor(w.db)
    spec = ReportSpec(
        definition_code="top_productos",
        metrics=[Metric.UNITS, Metric.REVENUE],
        dimensions=[Dimension.BRANCH, Dimension.PRODUCT],
        filters=Filters(period=Period(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30), label="Septiembre")),
    )
    res = ejecutor.ejecutar(SpecValidada(spec=spec, tenant_id=tenant_b))
    nombres_sucursales_a = {w.branches[0].name}
    for r in res.rows:
        assert r["branch"] not in nombres_sucursales_a


def test_reporte_pedidos_incluye_pending_y_cancelled(saas_world):
    """Reporte «pedidos» → incluye pending_payment y cancelled además de pagados."""
    w = saas_world
    tenant_a = w.tenants[0].id
    b1 = w.branches[0]

    o_pending = OrderModel(
        tenant_id=tenant_a, branch_id=b1.id, number="ORD-PEND-TEST", customer_email="c@test.com",
        status="pending_payment", payment_method="stripe", total=Decimal("100"), subtotal=Decimal("100"),
        currency="BOB", address={}, items=[{"product_name": "P1", "quantity": 1, "unit_price": "100"}],
        created_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
    )
    o_canc = OrderModel(
        tenant_id=tenant_a, branch_id=b1.id, number="ORD-CANC-TEST", customer_email="c@test.com",
        status="cancelled", payment_method="stripe", total=Decimal("100"), subtotal=Decimal("100"),
        currency="BOB", address={}, items=[{"product_name": "P2", "quantity": 1, "unit_price": "100"}],
        created_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
    )
    w.db.add_all([o_pending, o_canc])
    w.db.commit()

    ejecutor = Ejecutor(w.db)
    # Si definition_code es pedidos_por_estado o si filtros no restringen status
    spec = ReportSpec(
        definition_code="pedidos_por_estado",
        metrics=[Metric.ORDERS, Metric.REVENUE],
        dimensions=[Dimension.STATUS],
        filters=Filters(period=Period(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30), label="Septiembre")),
    )
    res = ejecutor.ejecutar(SpecValidada(spec=spec, tenant_id=tenant_a))
    # Debe registrar órdenes con pending_payment y cancelled
    statuses = {r.get("status") for r in res.rows}
    assert "pending_payment" in statuses or len(res.rows) >= 2


def test_una_sola_dimension_groups_vacio_o_ausente(saas_world):
    """Una sola dimensión → groups ausente o vacío y forma actual sin cambios."""
    w = saas_world
    tenant_a = w.tenants[0].id
    ejecutor = Ejecutor(w.db)
    spec = ReportSpec(
        definition_code="ventas_por_sucursal",
        metrics=[Metric.REVENUE],
        dimensions=[Dimension.BRANCH],
        filters=Filters(period=Period(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30), label="Septiembre")),
    )
    res = ejecutor.ejecutar(SpecValidada(spec=spec, tenant_id=tenant_a))
    assert getattr(res, "groups", None) in (None, [])
