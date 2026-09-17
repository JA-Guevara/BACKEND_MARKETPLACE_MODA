"""Exportacion multiple de reportes para el dashboard.

Cada reporte llega YA calculado y validado por ``ReportsService.export_report``
(``title``, ``headers``, ``rows``) junto con los filtros que le aplican. Este
modulo solo serializa el conjunto autorizado en los tres formatos pedidos:

- xlsx: un unico archivo con una hoja por reporte y una hoja "Criterios".
- pdf: un unico documento con cabecera FashionStore, resumen de criterios y una
  seccion por reporte; los encabezados de tabla se repiten en paginas nuevas y
  las paginas se numeran.
- csv: un reporte => ``.csv``; varios => ``.zip`` con un CSV por reporte y un
  archivo de criterios. Nunca se concatenan tablas incompatibles en un CSV.

Las hojas/columnas usan los mismos encabezados legibles, importes numericos y
totales que el exportador individual, para mantener "dashboard = export".
"""
import csv
import io
import zipfile
from xml.sax.saxutils import escape
from datetime import datetime

from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from src.ventas_pagos.application.exporter import _safe, build_metadata, label, safe_value
from src.ventas_pagos.application.reports_service import BUSINESS_TZ

REPORTS_ORDER = ["ventas", "pedidos", "pagos", "prendas_vendidas", "existencias", "sucursales"]

REPORT_LABELS = {
    "ventas": "Ventas diarias (ingresos cobrados)",
    "pedidos": "Pedidos",
    "pagos": "Pagos confirmados",
    "prendas_vendidas": "Prendas vendidas",
    "existencias": "Existencias por sucursal",
    "sucursales": "Rendimiento por sucursal (ingresos cobrados)",
}

# Nombres cortos y unicos para las hojas de Excel (maximo 31 caracteres).
REPORT_SHEET_NAMES = {
    "ventas": "Ventas",
    "pedidos": "Pedidos",
    "pagos": "Pagos",
    "prendas_vendidas": "Prendas vendidas",
    "existencias": "Existencias",
    "sucursales": "Sucursales",
}

# Que filtros del dashboard se aplican Y a que fecha se atribuye cada reporte.
# Existencias no usa periodo/estado (es una fotografia del momento);
# el resto deriva de pedidos y respeta filtro de estado de pedido.
FILTER_APPLIES = {
    "ventas": {"periodo": True, "branch": True, "category": True, "status": True},
    "pedidos": {"periodo": True, "branch": True, "category": True, "status": True},
    "pagos": {"periodo": True, "branch": True, "category": True, "status": True},
    "prendas_vendidas": {"periodo": True, "branch": True, "category": True, "status": True},
    "existencias": {"periodo": False, "branch": True, "category": True, "status": False},
    "sucursales": {"periodo": True, "branch": True, "category": True, "status": True},
}

DATE_REFERENCE = {
    "ventas": "Ingresos: fecha de pago (paid_at) cuando existe; fecha de creacion en historicos.",
    "pedidos": "Fecha de creacion del pedido.",
    "pagos": "Fecha de pago (paid_at) cuando existe; fecha de creacion en historicos.",
    "prendas_vendidas": "Pedidos pagados del periodo; fecha de pago de la linea.",
    "existencias": "Fotografia del momento; sin ventana de periodo.",
    "sucursales": "Pedidos pagados del periodo; fecha de pago de la linea.",
}


def _criteria_rows(metadata: dict) -> list[tuple[str, str]]:
    return [
        ("Periodo", metadata.get("periodo", "-")),
        ("Filtros", metadata.get("filtros", "-")),
        ("Zona", metadata.get("zona", "America/La_Paz")),
        ("Moneda", metadata.get("moneda", "-")),
        ("Generado", metadata.get("generado", "-")),
        ("Nota", metadata.get("nota", "-")),
    ]


def _sheet_wide() -> tuple[str, str]:
    return "Criterios", "valor"


def _build_report_bundle(report, ctx: dict) -> dict:
    """Arma el bundle que consumen los serializadores: titulo, hoja, cabeceras,
    filas, filtros que aplican y referencia de fecha para los criterios."""
    key = report["key"]
    applies = FILTER_APPLIES[key]
    no_applies = [name for name, ok in applies.items() if not ok]
    extra = {
        "key": key,
        "sheet": REPORT_SHEET_NAMES[key],
        "no_aplica": ", ".join(no_applies) if no_applies else "ninguno",
        "referencia": DATE_REFERENCE[key],
    }
    return {**report, **extra}


def build_multi_xlsx(reports: list[dict], metadata: dict) -> io.BytesIO:
    """Un solo .xlsx con una hoja por reporte y la hoja "Criterios" de apertura."""
    workbook = Workbook()
    criteria_sheet = workbook.active
    criteria_sheet.title = "Criterios"
    criteria_sheet["A1"] = "Titulo"
    criteria_sheet["B1"] = metadata.get("titulo", "Reportes de FashionStore")
    header_fill = PatternFill("solid", fgColor="74394E")
    header_font = Font(color="FFFFFF", bold=True)
    for i, (key, value) in enumerate(_criteria_rows(metadata), start=2):
        criteria_sheet.cell(row=i, column=1, value=label(key))
        criteria_sheet["B" + str(i)] = safe_value(value)
    criteria_sheet["A8"] = "Reporte"
    criteria_sheet["B8"] = "Filtros que NO aplican"
    criteria_sheet["C8"] = "Referencia de fecha"
    for cell in criteria_sheet[8]:
        cell.fill = header_fill
        cell.font = header_font
    for idx, bundle in enumerate(reports):
        row = 9 + idx
        criteria_sheet.cell(row=row, column=1, value=bundle["title"])
        criteria_sheet.cell(row=row, column=2, value=bundle["no_aplica"])
        criteria_sheet.cell(row=row, column=3, value=bundle["referencia"])
    criteria_sheet.column_dimensions["A"].width = 24
    criteria_sheet.column_dimensions["B"].width = 90
    criteria_sheet.column_dimensions["C"].width = 70

    for bundle in reports:
        sheet = workbook.create_sheet(bundle["sheet"])
        sheet.freeze_panes = "A2"
        headers = bundle["headers"]
        sheet.append([label(key) for key in headers])
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = header_font
        for row in bundle["rows"]:
            sheet.append([safe_value(row.get(key, "")) for key in headers])
        widths_by_key: dict[str, int] = {}
        for row in bundle["rows"]:
            for key in headers:
                widths_by_key[key] = max(widths_by_key.get(key, 0), len(str(row.get(key, ""))))
        widths = [max(widths_by_key.get(key, 0), len(label(key))) + 2 for key in headers]
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[get_column_letter(index)].width = min(width, 42)

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


def build_csv_single(bundle: dict, metadata: dict) -> bytes:
    """CSV individual, con la misma cabecera de metadatos que el exportador
    previo para no romper el contrato del endpoint individual."""
    headers, rows = bundle["headers"], bundle["rows"]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    buf.write("# " + bundle["title"] + "\n")
    for key in ("periodo", "filtros", "zona", "moneda", "generado", "nota"):
        val = metadata.get(key, "-")
        buf.write(f"# {label(key)}: {val}\n")
    buf.write(f"# Filtros que NO aplican: {bundle['no_aplica']}\n")
    buf.write(f"# Referencia de fecha: {bundle['referencia']}\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_safe(row.get(key, "")) for key in headers])
    return buf.getvalue().encode("utf-8-sig")


def build_csv_zip(bundles: list[dict], metadata: dict) -> io.BytesIO:
    """Varios reportes => un .zip con un CSV por reporte y criterios.txt.
    Nunca se concatenan tablas incompatibles en un mismo CSV."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        criterios = io.StringIO()
        criterios.write("Reportes de FashionStore - criterios de exportacion\n")
        for key, value in _criteria_rows(metadata):
            criterios.write(f"{label(key)}: {value}\n")
        for idx, bundle in enumerate(bundles, start=1):
            csv_bytes = build_csv_single(bundle, metadata)
            archive.writestr(f"{idx:02d}_{bundle['key']}.csv", csv_bytes)
        archive.writestr("criterios.txt", criterios.getvalue())
    output.seek(0)
    return output


def _pdf_text(value) -> str:
    """Helvetica es Latin-1: quita cualquier caracter fuera de rango para que
    un nombre con simbolo no rompa la generacion del PDF."""
    if not isinstance(value, str):
        value = str(value)
    return escape(_safe(value).encode("latin-1", "replace").decode("latin-1"))


def _chart_for(key: str, headers: list[str], rows: list[dict], width: float, height: float):
    """Un grafico pertinente generado con los MISMOS datos de la tabla, cuando
    el reporte lo soporta. Cliente de esta funcion: solo "ventas" y
    "sucursales" tienen una dimension ordinal + importe natural de graficar."""
    from reportlab.graphics import renderPDF

    def numeric(label_key: str):
        return label_key in {"total", "ingresos"}

    if key == "ventas":
        try:
            date_i, total_i = headers.index("fecha"), headers.index("total")
        except ValueError:
            return None
        items = rows[-15:]
        if not items:
            return None
        drawing = Drawing(width, height)
        chart = VerticalBarChart()
        chart.x = 50
        chart.y = 34
        chart.width = width - 70
        chart.height = height - 55
        chart.data = [[float(_pdf_text(r["total"]).replace(",", ".")) or 0 for r in items]]
        chart.categoryAxis.categoryNames = [_pdf_text(r["fecha"])[5:10] for r in items]
        chart.categoryAxis.labels.fontSize = 6
        chart.categoryAxis.labels.angle = 30
        chart.valueAxis.valueMin = 0
        chart.bars[0].fillColor = colors.HexColor("#74394E")
        drawing.add(chart)
        return Image(drawing, width=width, height=height)
    if key == "sucursales":
        try:
            branch_i, total_i = headers.index("sucursal"), headers.index("ingresos")
        except ValueError:
            return None
        items = rows[:8]
        if not items:
            return None
        drawing = Drawing(width, height)
        chart = HorizontalBarChart()
        chart.x = 90
        chart.y = 30
        chart.width = width - 110
        chart.height = height - 55
        values = [float(_pdf_text(r["ingresos"]).replace(",", ".")) or 0 for r in items]
        chart.data = [values]
        labels = [_pdf_text(r["sucursal"])[:24] for r in items]
        chart.categoryAxis.categoryNames = labels
        chart.categoryAxis.labels.fontSize = 7
        chart.valueAxis.valueMin = 0
        chart.bars[0].fillColor = colors.HexColor("#74394E")
        drawing.add(chart)
        return Image(drawing, width=width, height=height)
    return None


def build_multi_pdf(reports: list[dict], metadata: dict) -> io.BytesIO:
    """Un solo PDF con cabecera, criterios y una seccion por reporte."""
    output = io.BytesIO()
    wide = any(len(bundle["headers"]) > 5 for bundle in reports)
    page_size = landscape(letter) if wide else letter

    doc = BaseDocTemplate(
        output,
        pagesize=page_size,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="FashionStore - Reportes",
        author="FashionStore",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")

    def on_page(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#645d55"))
        canvas.drawString(d.leftMargin, 8 * mm, "FashionStore")
        canvas.drawRightString(d.leftMargin + d.width, 8 * mm, f"Pagina {d.page}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=on_page)])

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.HexColor("#24231f")))
    styles.add(ParagraphStyle(name="Meta", fontName="Helvetica", fontSize=8, leading=11, textColor=colors.HexColor("#645d55")))
    styles.add(ParagraphStyle(name="Crit", fontName="Helvetica", fontSize=8, leading=11, textColor=colors.HexColor("#24231f")))
    styles.add(ParagraphStyle(name="Sec", fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=10, textColor=colors.HexColor("#24231f")))
    styles.add(ParagraphStyle(name="Nota", fontName="Helvetica-Oblique", fontSize=7.5, leading=10, textColor=colors.HexColor("#756c62"), spaceAfter=4))
    styles.add(ParagraphStyle(name='Cell', fontName='Helvetica', fontSize=8, leading=10, wordWrap='CJK'))
    styles.add(ParagraphStyle(name='CellHead', parent=styles['Cell'], fontName='Helvetica-Bold', textColor=colors.white))

    story = [
        Paragraph("FashionStore - Reportes de la tienda", styles["H1"]),
        Spacer(1, 4),
Paragraph(
                f"Periodo: {_pdf_text(metadata.get('periodo', '-'))} &nbsp;&middot;&nbsp; "
                f"Zona: {_pdf_text(metadata.get('zona', '-'))} &nbsp;&middot;&nbsp; "
                f"Moneda: {_pdf_text(metadata.get('moneda', '-'))} &nbsp;&middot;&nbsp; "
                f"Generado: {_pdf_text(metadata.get('generado', '-'))}",
                styles["Meta"],
            ),
        Spacer(1, 4),
    ]
    if metadata.get("filtros"):
        story.append(Paragraph(f"Filtros aplicados: {_pdf_text(metadata.get('filtros', '-'))}", styles["Meta"]))
    note = metadata.get("nota", "")
    if note:
        story.append(Paragraph(_pdf_text(note), styles["Meta"]))

    for idx, bundle in enumerate(reports, start=1):
        story.append(Paragraph(f"{idx}. {_pdf_text(bundle['title'])}", styles["Sec"]))
        if bundle.get("no_aplica") not in (None, "", "ninguno"):
            story.append(Paragraph(f"No aplican a este reporte: {_pdf_text(bundle['no_aplica'])}. {_pdf_text(bundle.get('referencia', ''))}", styles["Nota"]))
        headers, rows = bundle["headers"], bundle["rows"]
        data = [[Paragraph(_pdf_text(label(key)), styles['CellHead']) for key in headers]]
        for row in rows:
            data.append([Paragraph(_pdf_text(row.get(key, '')), styles['Cell']) for key in headers])
        if not rows:
            story.append(Paragraph("Sin datos para el periodo y filtros seleccionados.", styles["Meta"]))
        col_widths = []
        usable = doc.width
        text_lens = []
        for key in headers:
            max_len = len(label(key))
            for row in rows[:200]:
                max_len = max(max_len, len(_pdf_text(row.get(key, ""))))
            text_lens.append(max_len)
        total_len = sum(text_lens) or 1
        for length in text_lens:
            col_widths.append(max(24 * mm, usable * (length / max(total_len, 1))))
        if len(col_widths) > 1:
            col_widths = [w * (usable / sum(col_widths)) for w in col_widths]
        table = Table(data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#74394E")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5ded5")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(table)
        chart = _chart_for(bundle["key"], headers, rows, doc.width, 44 * mm)
        if chart is not None:
            story.append(Spacer(1, 3))
            story.append(chart)
        if idx < len(reports):
            story.append(PageBreak())

    doc.build(story)
    output.seek(0)
    return output
