"""CU-29 · Exportacion convencional a PDF en /analytics/reports/export.

El PDF reutiliza el generador de reportes con IA (Exportador.pdf) y respeta
la empresa del token (RN03): la empresa B nunca ve pedidos de la empresa A.
"""
import base64
import re
import zlib
from datetime import datetime, timezone
from decimal import Decimal

from src.ventas_pagos.infrastructure.models import OrderModel


def _texto_pdf(content: bytes) -> str:
    """Decodifica los streams (ASCII85 + FlateDecode de ReportLab) para buscar texto plano."""
    partes = [content.decode("latin-1")]
    for raw in re.findall(rb"stream\r?\n(.*?)\r?\n?endstream", content, re.S):
        data = raw.strip()
        try:
            if data.endswith(b"~>"):
                data = base64.a85decode(data[:-2].replace(b"\n", b"").replace(b"\r", b""))
            partes.append(zlib.decompress(data).decode("latin-1"))
        except (zlib.error, ValueError):
            continue
    return "\n".join(partes)


def _sembrar_pedido(w, idx: int, numero: str, correo: str) -> None:
    w.db.add(OrderModel(
        tenant_id=w.tenants[idx].id,
        branch_id=w.branches[idx].id,
        number=numero,
        customer_email=correo,
        status="paid",
        payment_status="paid",
        payment_method="cash",
        total=Decimal("250.00"),
        subtotal=Decimal("250.00"),
        currency="BOB",
        address={},
        items=[{"product_name": "Vestido", "quantity": 1, "unit_price": "250.00", "line_total": "250.00"}],
        created_at=datetime.now(timezone.utc),
    ))
    w.db.commit()


def test_export_pdf_convencional_y_aislamiento_por_empresa(saas_world):
    w = saas_world
    _sembrar_pedido(w, 0, "ORDPDFA01", "compradora.a@test.com")
    _sembrar_pedido(w, 1, "ORDPDFB01", "comprador.b@test.com")

    resp_a = w.client.get(
        "/api/v1/analytics/reports/export",
        headers=w.headers(w.admins[0]),
        params={"report": "pedidos", "format": "pdf", "status": "paid"},
    )
    assert resp_a.status_code == 200, resp_a.text
    assert resp_a.headers["content-type"].startswith("application/pdf")
    assert resp_a.content.startswith(b"%PDF")
    assert ".pdf" in resp_a.headers["content-disposition"]
    texto_a = _texto_pdf(resp_a.content)
    assert "MODA A" in texto_a  # empresa del token
    assert "Pedidos" in texto_a  # titulo del reporte
    assert "Filtros" in texto_a and "estado=paid" in texto_a  # filtros aplicados
    assert "Generado el" in texto_a  # fecha de generacion
    assert "Numero" in texto_a  # encabezados de tabla
    assert "ORDPDFA01" in texto_a
    assert "ORDPDFB01" not in texto_a

    resp_b = w.client.get(
        "/api/v1/analytics/reports/export",
        headers=w.headers(w.admins[1]),
        params={"report": "pedidos", "format": "pdf"},
    )
    assert resp_b.status_code == 200, resp_b.text
    assert resp_b.content.startswith(b"%PDF")
    texto_b = _texto_pdf(resp_b.content)
    assert "MODA B" in texto_b
    assert "ORDPDFB01" in texto_b
    assert "ORDPDFA01" not in texto_b
    assert "compradora.a@test.com" not in texto_b


def test_export_formato_desconocido_sigue_rechazado(saas_world):
    w = saas_world
    resp = w.client.get(
        "/api/v1/analytics/reports/export",
        headers=w.headers(w.admins[0]),
        params={"report": "pedidos", "format": "docx"},
    )
    assert resp.status_code == 422
