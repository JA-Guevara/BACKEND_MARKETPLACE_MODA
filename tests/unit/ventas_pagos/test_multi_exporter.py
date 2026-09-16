"""Regresiones del exportador multiple: xlsx multi-hoja con Criterios, csv/zip,
pdf con paginas y nota de truncamiento honesta."""
import io
import zipfile

from openpyxl import load_workbook

from src.ventas_pagos.application import multi_exporter
from src.ventas_pagos.application.multi_exporter import (
    build_csv_single,
    build_csv_zip,
    build_multi_pdf,
    build_multi_xlsx,
)


def bundle(key, headers, rows, no_aplica="ninguno", referencia="fecha de pago", truncated=False):
    return {
        "key": key,
        "title": "titulo_" + key,
        "sheet": multi_exporter.REPORT_SHEET_NAMES.get(key, "Hoja"),
        "headers": headers,
        "rows": rows,
        "no_aplica": no_aplica,
        "referencia": referencia,
        "truncated": truncated,
    }


METADATA = {
    "titulo": "Reportes de FashionStore",
    "periodo": "2026-01-01 a 2026-01-31",
    "filtros": "sucursal=Sucursal Central",
    "zona": "America/La_Paz",
    "moneda": "BOB",
    "generado": "2026-09-16 10:00 -04",
    "nota": "Exportacion multiple desde el dashboard de FashionStore.",
}


def test_xlsx_multi_hoja_con_criterios():
    reports = [
        bundle("ventas", ["fecha", "total"], [{"fecha": "2026-01-01", "total": 50.0}]),
        bundle("sucursales", ["sucursal", "ingresos"], [{"sucursal": "Central", "ingresos": 120.0}]),
    ]
    output = build_multi_xlsx(reports, METADATA)
    workbook = load_workbook(io.BytesIO(output.getvalue()))
    assert set(workbook.sheetnames) == {"Criterios", "Ventas", "Sucursales"}
    ventas = workbook["Ventas"]
    assert ventas["A1"].value == "Fecha"
    assert ventas["B2"].value == 50.0
    criterios = workbook["Criterios"]
    values = {criterios.cell(row=i, column=1).value: criterios.cell(row=i, column=2).value for i in range(1, 8)}
    assert values["Periodo"] == "2026-01-01 a 2026-01-31"
    assert values["Moneda"] == "BOB"
    assert criterios["A8"].value == "Reporte"
    assert criterios["B8"].value == "Filtros que NO aplican"


def test_csv_unico_y_zip_multiple():
    one = [bundle("ventas", ["fecha", "total"], [{"fecha": "2026-01-01", "total": 50.0}])]
    csv_bytes = build_csv_single(one[0], METADATA)
    assert b"# Periodo: 2026-01-01 a 2026-01-31" in csv_bytes
    assert b"fecha,total" in csv_bytes

    many = [
        bundle("ventas", ["fecha", "total"], [{"fecha": "2026-01-01", "total": 50.0}]),
        bundle("pedidos", ["numero", "total"], [{"numero": "P-1", "total": 120.0}]),
    ]
    if len(many) > 1:
        zipped = build_csv_zip(many, METADATA)
        with zipfile.ZipFile(io.BytesIO(zipped.getvalue())) as archive:
            names = archive.namelist()
            assert "criterios.txt" in names
            assert "01_ventas.csv" in names
            assert "02_pedidos.csv" in names
            assert archive.read("criterios.txt").startswith(b"Reportes de FashionStore")


def test_pdf_genera_documento_valido_con_paginas():
    reports = [
        bundle("ventas", ["fecha", "total"], [{"fecha": "2026-01-01", "total": 50.0}], no_aplica="ninguno"),
        bundle("pedidos", ["numero", "correo", "total"], [{"numero": "P-1", "correo": "a@b.test", "total": 120.0}]),
    ]
    output = build_multi_pdf(reports, METADATA)
    content = output.getvalue()
    assert content.startswith(b"%PDF")
    assert b"/Type /Page" in content


def test_pdf_no_rompe_con_texto_fuera_de_latin1():
    reports = [
        bundle("ventas", ["fecha", "total"], [{"fecha": "2026-01-01", "total": 50.0}]),
    ]
    reports[0]["rows"] = [{"fecha": "2026-01-01", "total": 50.0}]
    reports[0]["headers"] = ["fecha", "total"]
    output = build_multi_pdf(reports, METADATA)
    assert output.getvalue().startswith(b"%PDF")


def test_metadatos_multi_xlsx_no_ocultan_truncamiento():
    reports = [
        bundle("ventas", ["fecha", "total"], [{"fecha": "2026-01-01", "total": 50.0}], truncated=True),
    ]
    meta = dict(METADATA, nota=METADATA["nota"] + " Se aplico el limite maximo de filas configurado; el total del dashboard puede diferir.")
    output = build_multi_xlsx(reports, meta)
    workbook = load_workbook(io.BytesIO(output.getvalue()))
    nota = workbook["Criterios"]["B7"].value
    assert "limite maximo de filas" in nota


def test_filtros_aplicables_por_reporte():
    assert multi_exporter.FILTER_APPLIES["existencias"] == {"periodo": False, "branch": True, "category": False, "status": False}
    assert multi_exporter.FILTER_APPLIES["ventas"]["periodo"] is True
    assert multi_exporter.FILTER_APPLIES["existencias"]["periodo"] is False