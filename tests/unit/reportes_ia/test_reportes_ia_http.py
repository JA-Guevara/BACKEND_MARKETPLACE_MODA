from datetime import date, datetime, timezone
from decimal import Decimal
import pytest

from src.reportes_ia.domain.especificacion import Dimension, Filters, Metric, Period, ReportSpec
from src.ventas_pagos.infrastructure.models import OrderModel


def test_flujo_completo_reportes_ia_http(saas_world):
    w = saas_world
    # Admin 1 pertenece a Tenant 1 (Plan PROFESIONAL con ai_reports habilitado)
    admin_pro = w.admins[1]
    tenant_pro = w.tenants[1]
    headers = w.headers(admin_pro)

    # Sembrar un pedido pagado
    order = OrderModel(
        tenant_id=tenant_pro.id,
        branch_id=w.branches[1].id,
        number="ORD-HTTP-01",
        customer_email="cliente@test.com",
        status="paid",
        payment_method="cash",
        total=Decimal("300.00"),
        subtotal=Decimal("300.00"),
        currency="BOB",
        address={},
        items=[
            {
                "product_name": "Vestido Fiesta",
                "quantity": 1,
                "unit_price": "300.00",
                "line_total": "300.00",
                "category_name": "Vestidos B",
            }
        ],
        created_at=datetime.now(timezone.utc),
    )
    w.db.add(order)
    w.db.commit()

    # 1. Obtener definiciones
    resp_defs = w.client.get("/api/v1/analytics/ai-reports/definitions", headers=headers)
    assert resp_defs.status_code == 200, resp_defs.text
    defs_data = resp_defs.json()["data"]
    codes = [d["code"] for d in defs_data]
    assert "ventas_por_sucursal" in codes
    assert "top_productos" in codes

    # 2. Interpretar consulta en lenguaje natural
    resp_inter = w.client.post(
        "/api/v1/analytics/ai-reports/interpret",
        headers=headers,
        json={"text": "Mostrame las ventas agrupadas por sucursal este mes", "channel": "TEXT"},
    )
    assert resp_inter.status_code == 200, resp_inter.text
    inter_data = resp_inter.json()["data"]
    assert inter_data["status"] == "READY"
    assert "request_id" in inter_data
    request_id = inter_data["request_id"]
    spec = inter_data["spec"]
    assert spec["definition_code"] == "ventas_por_sucursal"

    # 3. Ejecutar reporte con la especificación interpretada
    resp_run = w.client.post(
        "/api/v1/analytics/ai-reports/run",
        headers=headers,
        json={"spec": spec, "request_id": request_id},
    )
    assert resp_run.status_code == 200, resp_run.text
    run_data = resp_run.json()["data"]
    assert run_data["definition_code"] == "ventas_por_sucursal"
    assert "narrative" in run_data
    assert len(run_data["rows"]) >= 1

    # 4. Exportar a XLSX
    resp_export = w.client.post(
        "/api/v1/analytics/ai-reports/export",
        headers=headers,
        json={"spec": spec, "format": "xlsx", "request_id": request_id},
    )
    assert resp_export.status_code == 200
    assert "application/vnd.openxmlformats" in resp_export.headers.get("content-type", "")
    assert len(resp_export.content) > 100

    # 5. Exportar a CSV
    resp_csv = w.client.post(
        "/api/v1/analytics/ai-reports/export",
        headers=headers,
        json={"spec": spec, "format": "csv", "request_id": request_id},
    )
    assert resp_csv.status_code == 200
    assert "text/csv" in resp_csv.headers.get("content-type", "")

    # 6. Consultar historial
    resp_hist = w.client.get("/api/v1/analytics/ai-reports/history", headers=headers)
    assert resp_hist.status_code == 200, resp_hist.text
    hist_data = resp_hist.json()["data"]
    assert hist_data["total"] >= 1
    assert hist_data["items"][0]["status"] in ("EXECUTED", "EXPORTED")


def test_pregunta_6_examen_literal(saas_world):
    w = saas_world
    admin_pro = w.admins[1]
    tenant_pro = w.tenants[1]
    headers = w.headers(admin_pro)

    # Crear una segunda sucursal para tenant_pro para verificar agrupación
    import uuid
    from src.inventario_sucursales.infrastructure.models.organization import BranchModel
    branch2 = BranchModel(
        id=uuid.uuid4(),
        tenant_id=tenant_pro.id,
        name="Sucursal Norte",
        code="SUC-NORTE",
        address="Av. Banzer Km 5",
        city_id=w.branches[1].city_id,
        is_active=True,
    )
    w.db.add(branch2)
    w.db.commit()

    # Sembrar pedidos pagados en dos sucursales distintas
    order1 = OrderModel(
        tenant_id=tenant_pro.id,
        branch_id=w.branches[1].id,
        number="ORD-EXAM-01",
        customer_email="cliente1@test.com",
        status="paid",
        payment_method="cash",
        total=Decimal("600.00"),
        subtotal=Decimal("600.00"),
        currency="BOB",
        address={},
        items=[
            {
                "product_name": "Vestido Fiesta",
                "quantity": 2,
                "unit_price": "300.00",
                "line_total": "600.00",
                "category_name": "Vestidos",
            }
        ],
        created_at=datetime.now(timezone.utc),
    )
    order2 = OrderModel(
        tenant_id=tenant_pro.id,
        branch_id=branch2.id,
        number="ORD-EXAM-02",
        customer_email="cliente2@test.com",
        status="paid",
        payment_method="cash",
        total=Decimal("450.00"),
        subtotal=Decimal("450.00"),
        currency="BOB",
        address={},
        items=[
            {
                "product_name": "Camisa Lino",
                "quantity": 3,
                "unit_price": "150.00",
                "line_total": "450.00",
                "category_name": "Camisas",
            }
        ],
        created_at=datetime.now(timezone.utc),
    )
    w.db.add_all([order1, order2])
    w.db.commit()

    # Consulta literal del Examen Parcial (Pregunta 6)
    texto_examen = "mostrar los 10 productos mas vendidos durante los ultimos 3 meses agrupados por sucursal"

    resp_inter = w.client.post(
        "/api/v1/analytics/ai-reports/interpret",
        headers=headers,
        json={"text": texto_examen, "channel": "TEXT"},
    )
    assert resp_inter.status_code == 200, resp_inter.text
    inter_data = resp_inter.json()["data"]
    assert inter_data["status"] == "READY"
    spec = inter_data["spec"]
    assert spec["definition_code"] == "top_productos"
    assert "PRODUCT" in spec["dimensions"]
    assert "BRANCH" in spec["dimensions"]
    assert spec["top_n"] == 10

    # Ejecutar reporte
    resp_run = w.client.post(
        "/api/v1/analytics/ai-reports/run",
        headers=headers,
        json={"spec": spec, "request_id": inter_data["request_id"]},
    )
    assert resp_run.status_code == 200, resp_run.text
    run_data = resp_run.json()["data"]
    assert run_data["definition_code"] == "top_productos"
    assert len(run_data["rows"]) >= 2

    # Verificar que las columnas incluyen Sucursal y Producto
    col_keys = [c["key"] for c in run_data["columns"]]
    assert "branch" in col_keys
    assert "product" in col_keys
    assert "units" in col_keys
    assert "revenue" in col_keys

    # Verificar narrativa generada
    assert "narrative" in run_data
    assert len(run_data["narrative"]) > 10
