"""Casos de uso de exportacion multiple del dashboard.

Genera los archivos (xlsx/pdf/csv/zip) a partir de los reportes calculados por
``ReportsService.export_report`` con criterios normalizados, aplica el limite
de filas por reporte (nunca oculta el truncamiento) y expone resumen legible
para la bitacora y para los encabezados de respuesta.
"""
import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.infrastructure.config.settings import settings
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.usuarios_catalogo.infrastructure.models.catalog import CategoryModel
from src.ventas_pagos.application import multi_exporter
from src.ventas_pagos.application.reports_service import BUSINESS_TZ, ReportsService
from src.ventas_pagos.web.schemas import ReportFilters

ExportFormat = Literal["xlsx", "pdf", "csv"]


def _filter_text(filters: ReportFilters, db: Session, branch_name: str | None, category_name: str | None) -> str:
    parts = []
    if filters.date_from or filters.date_to:
        parts.append(f"desde={filters.date_from.isoformat() if filters.date_from else '-'}")
        parts.append(f"hasta={filters.date_to.isoformat() if filters.date_to else '-'}")
    if filters.branch_id:
        parts.append(f"sucursal={branch_name or filters.branch_id}")
    if filters.category_id:
        parts.append(f"categoria={category_name or filters.category_id}")
    if filters.status:
        parts.append(f"estado={filters.status}")
    return "; ".join(parts) if parts else "sin filtros adicionales"


class MultiExportService:
    """Ejecuta la exportacion multiple autorizada y devuelve el contenido listo
    para enviar: (payload, media_type, filename, summary)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _report_bundle(self, key: str, filters: ReportFilters) -> dict:
        title, headers, rows = ReportsService(self.db).export_report(
            key,
            filters.date_from,
            filters.date_to,
            filters.branch_id,
            filters.category_id,
            filters.status,
        )
        truncated = len(rows) > settings.report_export_max_rows
        rows = rows[: settings.report_export_max_rows]
        bundle = multi_exporter._build_report_bundle(
            {"key": key, "title": title, "headers": headers, "rows": rows}, None
        )
        bundle["truncated"] = truncated
        return bundle

    def export(
        self,
        reports: list[str],
        format: ExportFormat,
        filters: ReportFilters | None = None,
    ) -> tuple[object, str, str, dict]:
        filters = filters or ReportFilters()
        # Filtros normalizados siempre desde el servidor.
        start, end = ReportsService(self.db)._window(filters.date_from, filters.date_to)
        period_text = (
            f"{start.isoformat() if start else 'inicio'} a {end.isoformat() if end else 'hoy'}"
        )
        branch = self.db.scalar(select(BranchModel).where(BranchModel.id == filters.branch_id)) if filters.branch_id else None
        category = self.db.scalar(select(CategoryModel).where(CategoryModel.id == filters.category_id)) if filters.category_id else None
        filtro_text = _filter_text(filters, self.db, branch.name if branch else None, category.name if category else None)

        bundles = [self._report_bundle(key, filters) for key in reports]

        truncated = any(b["truncated"] for b in bundles)
        metadata = {
            "titulo": "Reportes seleccionados de FashionStore",
            "periodo": period_text,
            "filtros": filtro_text,
            "zona": "America/La_Paz",
            "moneda": settings.commerce_currency.upper(),
            "generado": datetime.now(BUSINESS_TZ).strftime("%Y-%m-%d %H:%M %Z"),
            "nota": (
                "Exportacion multiple desde el dashboard de FashionStore. Los totales coinciden "
                "con el dashboard para los mismos filtros aplicados."
                + (" Se aplico el limite maximo de filas configurado; el total del dashboard puede diferir." if truncated else "")
            ),
        }

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        labels = [multi_exporter.REPORT_LABELS[b["key"]] for b in bundles]
        summary = {
            "reports": labels,
            "format": format,
            "periodo": period_text,
            "filtros": filtro_text,
            "moneda": settings.commerce_currency.upper(),
            "truncated": truncated,
            "rows": [{"report": b["key"], "rows": len(b["rows"]), "truncated": b["truncated"]} for b in bundles],
        }

        if format == "xlsx":
            payload = multi_exporter.build_multi_xlsx(bundles, metadata)
            return payload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"fashionstore_reportes_{stamp}.xlsx", summary
        if format == "pdf":
            payload = multi_exporter.build_multi_pdf(bundles, metadata)
            return payload, "application/pdf", f"fashionstore_reportes_{stamp}.pdf", summary
        if len(bundles) == 1:
            payload = multi_exporter.build_csv_single(bundles[0], metadata)
            return payload, "text/csv; charset=utf-8", f"fashionstore_{bundles[0]['key']}_{stamp}.csv", summary
        payload = multi_exporter.build_csv_zip(bundles, metadata)
        return payload, "application/zip", f"fashionstore_reportes_{stamp}.zip", summary