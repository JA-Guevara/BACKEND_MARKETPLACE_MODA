from datetime import date
from io import BytesIO
from typing import Annotated, Literal
from xml.sax.saxutils import escape
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_platform_permissions
from src.plataforma_saas.application.analytics_service import PlatformAnalyticsService
from src.shared.responses.api_response import ApiResponse
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent

router = APIRouter(prefix="/platform/analytics", tags=["PAQ-06 · Consola SaaS"])
Reader = Annotated[UserModel, Depends(require_platform_permissions("subscriptions.read", "tenants.read"))]


def filters(date_from: date | None = None, date_to: date | None = None,
            plan_code: str | None = Query(None, max_length=30),
            state: Literal["ACTIVA", "INACTIVA", "SUSPENDIDA"] | None = None,
            horizon: int = Query(14, ge=1, le=30)):
    return dict(start=date_from, end=date_to, plan_code=plan_code, state=state, horizon=horizon)


@router.get("", response_model=ApiResponse[dict])
def dashboard(actor: Reader, query: Annotated[dict, Depends(filters)], db: Session = Depends(get_db)):
    return ApiResponse(data=PlatformAnalyticsService(db).report(**query))


@router.get("/export")
def export(actor: Reader, query: Annotated[dict, Depends(filters)],
           format: Literal["csv", "xlsx", "pdf"] = "xlsx", db: Session = Depends(get_db)):
    data = PlatformAnalyticsService(db).report(**query)
    headings = ["Empresa", "Plan", "Estado", "Vencimiento", "Cobrado BOB", "MRR estimado BOB", "Volumen comercial BOB", "Ventas pagadas"]
    rows = [[row[key] for key in ("name", "plan", "state", "end_date", "collected", "mrr_estimate", "sales_volume", "paid_sales")] for row in data["companies"]]
    def safe(value):
        text = str(value or "")
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text
    if format == "csv":
        import csv
        from io import StringIO
        stream = StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["Período", data["meta"]["from"], data["meta"]["to"], data["meta"]["note"]])
        writer.writerow(headings)
        writer.writerows([[safe(value) for value in row] for row in rows])
        payload, media = stream.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8"
    elif format == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.chart import LineChart, PieChart, Reference
        wb = Workbook()
        sheet = wb.active
        sheet.title = "Empresas"
        sheet.append(["FashionStore · Reporte de plataforma", data["meta"]["from"], data["meta"]["to"]])
        sheet.append([data["meta"]["note"]])
        sheet.append(headings)
        for row in rows:
            sheet.append([safe(value) if index<4 else float(value) for index,value in enumerate(row)])
        sheet.freeze_panes = "A4"
        sheet.auto_filter.ref = f"A3:H{max(3,sheet.max_row)}"
        for cell in sheet[3]:
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = PatternFill("solid", fgColor="204D60")
        for column in "ABCDEFGH":
            sheet.column_dimensions[column].width = 25
        trend = wb.create_sheet("Cobros y tendencia")
        trend.append(["Fecha", "Cobro real BOB", "Proyección estimada BOB"])
        for point in data["daily_collections"]:
            trend.append([point["date"], float(point["value"]), None])
        for point in data["projection"]["points"]:
            trend.append([point["date"], None, float(point["value"])])
        chart = LineChart()
        chart.title = "Cobros registrados y estimación"
        chart.add_data(Reference(trend, min_col=2, max_col=3, min_row=1, max_row=trend.max_row), titles_from_data=True)
        chart.set_categories(Reference(trend, min_col=1, min_row=2, max_row=trend.max_row))
        trend.add_chart(chart, "E2")
        plans = wb.create_sheet("Distribución por plan")
        plans.append(["Plan", "Empresas"])
        for item in data["plans"]:
            plans.append([safe(item["label"]), item["value"]])
        if data["plans"]:
            pie = PieChart()
            pie.add_data(Reference(plans, min_col=2, min_row=1, max_row=plans.max_row), titles_from_data=True)
            pie.set_categories(Reference(plans, min_col=1, min_row=2, max_row=plans.max_row))
            plans.add_chart(pie, "D2")
        out = BytesIO()
        wb.save(out)
        payload, media = out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        out = BytesIO()
        styles = getSampleStyleSheet()
        content = [Paragraph("FashionStore · Analítica de plataforma", styles["Title"]),
                   Paragraph(escape(f'{data["meta"]["from"]} a {data["meta"]["to"]} · America/La_Paz · BOB'), styles["Normal"]),
                   Paragraph(escape(data["meta"]["note"]), styles["Normal"]), Spacer(1, 14)]
        content.append(Paragraph(escape(f'Cobrado: Bs {data["kpis"]["collected"]} · MRR estimado: Bs {data["kpis"]["mrr_estimate"]}'), styles["Heading2"]))
        from reportlab.graphics.shapes import Drawing,String
        from reportlab.graphics.charts.piecharts import Pie
        from reportlab.graphics.charts.lineplots import LinePlot
        graphics=Drawing(690,240)
        if data['plans']:
            pie=Pie();pie.x=510;pie.y=60;pie.width=150;pie.height=150
            pie.data=[row['value'] for row in data['plans']]
            pie.labels=[f"{row['label']}: {row['value']}" for row in data['plans']]
            pie.sideLabels=True;pie.slices.strokeColor=colors.white
            palette=['#773c57','#204d60','#147d72','#b68840','#6782a4']
            for index in range(len(pie.data)):pie.slices[index].fillColor=colors.HexColor(palette[index%len(palette)])
            graphics.add(pie)
        points=data['daily_collections'];projected=data['projection']['points']
        if points:
            plot=LinePlot();plot.x=42;plot.y=42;plot.width=380;plot.height=160
            plot.data=[[(i,float(row['value'])) for i,row in enumerate(points)]]
            if projected:plot.data.append([(len(points)-1,float(points[-1]['value']))]+[(len(points)+i,float(row['value'])) for i,row in enumerate(projected)])
            plot.lines[0].strokeColor=colors.HexColor('#773c57')
            if projected:plot.lines[1].strokeColor=colors.HexColor('#147d72');plot.lines[1].strokeDashArray=[4,3]
            plot.xValueAxis.valueMin=0;plot.xValueAxis.valueMax=max(1,len(points)+len(projected)-1)
            plot.xValueAxis.valueSteps=[0,max(1,len(points)-1),max(1,len(points)+len(projected)-1)]
            dates=[row['date'] for row in points+projected]
            plot.xValueAxis.labelTextFormat=lambda value:dates[min(int(value),len(dates)-1)][5:]
            plot.yValueAxis.valueMin=0;plot.yValueAxis.labels.fontSize=8
            graphics.add(plot)
        graphics.add(String(42,220,'Cobros BOB y tendencia estimada',fontSize=10))
        graphics.add(String(510,220,'Empresas por plan',fontSize=10))
        content.extend([graphics,Paragraph(escape(data['projection']['note']),styles['Normal']),Spacer(1,12)])
        table = Table([[Paragraph(escape(str(value or "")), styles["Normal"]) for value in row] for row in [headings, *rows]], repeatRows=1, colWidths=[115,75,65,68,80,80,85,70])
        table.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,0),colors.HexColor("#E7EFF3")),("VALIGN",(0,0),(-1,-1),"TOP"),("GRID",(0,0),(-1,-1),0.3,colors.lightgrey)]))
        content.append(table)
        SimpleDocTemplate(out, pagesize=landscape(A4)).build(content)
        payload, media = out.getvalue(), "application/pdf"
    RecordAuditEvent(db).execute(action="platform.analytics_exported", entity_type="platform_report",
        actor_user_id=actor.id, description="Exportación de indicadores de la plataforma.",
        metadata={"format": format, "from": data["meta"]["from"], "to": data["meta"]["to"], "rows": len(rows)})
    db.commit()
    return Response(payload, media_type=media, headers={"Content-Disposition": f'attachment; filename="fashionstore-plataforma.{format}"', "Cache-Control": "no-store"})
