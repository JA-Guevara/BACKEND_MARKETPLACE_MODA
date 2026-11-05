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
