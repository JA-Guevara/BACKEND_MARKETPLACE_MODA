import csv
import io
from datetime import datetime
from typing import Any
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.reportes_ia.application.ejecutor import ReportResult
from src.reportes_ia.domain.especificacion import ReportSpec
from src.shared.exceptions.domain_exception import ValidationError


class Exportador:
    def xlsx(self, spec: ReportSpec, result: ReportResult, empresa: str) -> bytes:
        if result.truncated:
            raise ValidationError("export_rows_exceeded: Supera el límite de filas para exportar.")

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporte"

        # Estilos
        font_header_empresa = Font(name="Arial", size=14, bold=True, color="1E293B")
        font_sub = Font(name="Arial", size=10, italic=True, color="64748B")
        font_col_header = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        fill_col_header = PatternFill(start_color="3B82F6", end_color="3B82F6", fill_type="solid")
        font_total = Font(name="Arial", size=11, bold=True, color="0F172A")
        fill_total = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
        thin_border = Border(
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1"),
            top=Side(style="thin", color="CBD5E1"),
            bottom=Side(style="thin", color="CBD5E1"),
        )

        # Encabezado
        ws["A1"] = empresa.upper()
        ws["A1"].font = font_header_empresa
        ws["A2"] = f"Reporte: {result.title}"
        ws["A2"].font = Font(name="Arial", size=12, bold=True)
        ws["A3"] = f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        ws["A3"].font = font_sub

        curr_row = 5
        # Encabezados de columnas
        for col_idx, col in enumerate(result.columns, start=1):
            cell = ws.cell(row=curr_row, column=col_idx, value=col["label"])
            cell.font = font_col_header
            cell.fill = fill_col_header
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border
        curr_row += 1

        # Filas de datos
        for r in result.rows:
            for col_idx, col in enumerate(result.columns, start=1):
                val = r.get(col["key"], "")
                cell = ws.cell(row=curr_row, column=col_idx, value=val)
                cell.border = thin_border
                c_type = col.get("type", "text")
                if c_type == "money":
                    cell.number_format = '#,##0.00 "Bs"'
                    cell.alignment = Alignment(horizontal="right")
                elif c_type == "int":
                    cell.number_format = "#,##0"
                    cell.alignment = Alignment(horizontal="right")
                elif c_type == "pct":
                    cell.number_format = '0.0"%"'
                    cell.alignment = Alignment(horizontal="right")
                else:
                    cell.alignment = Alignment(horizontal="left")
            curr_row += 1

        # Fila de totales
        if result.totals:
            for col_idx, col in enumerate(result.columns, start=1):
                val = result.totals.get(col["key"], "")
                cell = ws.cell(row=curr_row, column=col_idx, value=val)
                cell.font = font_total
                cell.fill = fill_total
                cell.border = thin_border
                c_type = col.get("type", "text")
                if c_type == "money":
                    cell.number_format = '#,##0.00 "Bs"'
                    cell.alignment = Alignment(horizontal="right")
                elif c_type == "int":
                    cell.number_format = "#,##0"
                    cell.alignment = Alignment(horizontal="right")
                elif c_type == "pct":
                    cell.number_format = '0.0"%"'
                    cell.alignment = Alignment(horizontal="right")

        # Ajuste de ancho de columnas
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def pdf(self, spec: ReportSpec, result: ReportResult, empresa: str, narrativa: str = "") -> bytes:
        if result.truncated:
            raise ValidationError("export_rows_exceeded: Supera el límite de filas para exportar.")

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            name="TitleStyle",
            parent=styles["Heading1"],
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#1E293B"),
            spaceAfter=6,
        )
        sub_style = ParagraphStyle(
            name="SubStyle",
            parent=styles["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#64748B"),
            spaceAfter=12,
        )
        narrative_style = ParagraphStyle(
            name="NarrativeStyle",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#334155"),
            spaceAfter=14,
            backColor=colors.HexColor("#F8FAFC"),
            borderColor=colors.HexColor("#E2E8F0"),
            borderWidth=1,
            borderPadding=8,
        )

        elements = []
        elements.append(Paragraph(f"<b>{empresa.upper()}</b>", title_style))
        elements.append(Paragraph(f"Reporte: {result.title} · Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}", sub_style))

        if narrativa:
            elements.append(Paragraph(f"<b>Lectura inteligente:</b> {narrativa}", narrative_style))

        # Tabla
        headers = [col["label"] for col in result.columns]
        table_data = [headers]

        for r in result.rows:
            row_cells = []
            for col in result.columns:
                val = r.get(col["key"], "")
                c_type = col.get("type", "text")
                if c_type == "money" and isinstance(val, (int, float)):
                    row_cells.append(f"Bs {val:,.2f}")
                elif c_type == "int" and isinstance(val, (int, float)):
                    row_cells.append(f"{val:,}")
                elif c_type == "pct" and isinstance(val, (int, float)):
                    row_cells.append(f"{val:.1f}%")
                else:
                    row_cells.append(str(val))
            table_data.append(row_cells)

        # Fila de totales
        if result.totals:
            total_cells = []
            for col in result.columns:
                val = result.totals.get(col["key"], "")
                c_type = col.get("type", "text")
                if c_type == "money" and isinstance(val, (int, float)):
                    total_cells.append(f"Bs {val:,.2f}")
                elif c_type == "int" and isinstance(val, (int, float)):
                    total_cells.append(f"{val:,}")
                elif c_type == "pct" and isinstance(val, (int, float)):
                    total_cells.append(f"{val:.1f}%")
                else:
                    total_cells.append(str(val))
            table_data.append(total_cells)

        t = Table(table_data, repeatRows=1)
        t_style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563EB")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ]
        if result.totals:
            t_style.extend([
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F1F5F9")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ])
        t.setStyle(TableStyle(t_style))
        elements.append(t)

        elements.append(Spacer(1, 15))
        elements.append(Paragraph(f"<i>Datos de {empresa} · Consulta verificada por el sistema.</i>", sub_style))

        doc.build(elements)
        return buf.getvalue()

    def csv(self, spec: ReportSpec, result: ReportResult, empresa: str) -> bytes:
        if result.truncated:
            raise ValidationError("export_rows_exceeded: Supera el límite de filas para exportar.")

        output = io.StringIO()
        # UTF-8 BOM para Excel
        output.write('\ufeff')
        writer = csv.writer(output)

        writer.writerow([empresa])
        writer.writerow([f"Reporte: {result.title}"])
        writer.writerow([])
        writer.writerow([c["label"] for c in result.columns])

        for r in result.rows:
            writer.writerow([r.get(c["key"], "") for c in result.columns])

        if result.totals:
            writer.writerow([result.totals.get(c["key"], "") for c in result.columns])

        return output.getvalue().encode("utf-8")
