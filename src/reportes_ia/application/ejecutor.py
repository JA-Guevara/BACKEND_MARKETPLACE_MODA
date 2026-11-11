from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.reportes_ia.application.validador import SpecValidada
from src.reportes_ia.domain.especificacion import ChartKind, Dimension
from src.reportes_ia.domain.grafico import elegir_grafico
from src.reportes_ia.domain.texto import normalizar
from src.usuarios_catalogo.infrastructure.models.catalog import CategoryModel, ProductModel, ProductVariantModel
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel


BUSINESS_TZ = timezone(timedelta(hours=-4))


def _to_date(dt: datetime | date) -> date:
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            return dt.astimezone(BUSINESS_TZ).date()
        return dt.date()
    return dt


@dataclass
class ReportResult:
    definition_code: str
    title: str
    columns: list[dict[str, str]]
    rows: list[dict[str, Any]]
    totals: dict[str, Any]
    truncated: bool = False
    chart: dict[str, Any] = field(default_factory=dict)
    series: list[dict[str, Any]] = field(default_factory=list)


class Ejecutor:
    def __init__(self, db: Session) -> None:
        self.db = db

    def ejecutar(self, sv: SpecValidada, limite_filas: int = 500) -> ReportResult:
        code = sv.spec.definition_code
        if code == "ventas_por_sucursal":
            return self._ventas_por_sucursal(sv, limite_filas)
        elif code == "top_productos":
            return self._top_productos(sv, limite_filas)
        elif code == "ventas_por_semana":
            return self._ventas_por_semana(sv, limite_filas)
        elif code == "comparativa_sucursales":
            return self._comparativa_sucursales(sv, limite_filas)
        elif code == "menor_existencia":
            return self._menor_existencia(sv, limite_filas)
        elif code == "ingresos_por_categoria":
            return self._ingresos_por_categoria(sv, limite_filas)
        elif code in ("existencias", "stock"):
            return self._menor_existencia(sv, limite_filas)
        elif code in ("pagos", "formas_pago"):
            return self._pagos(sv, limite_filas)
        elif code in ("ventas", "ventas_diarias"):
            return self._ventas_por_semana(sv, limite_filas)
        elif code == "sucursales":
            return self._ventas_por_sucursal(sv, limite_filas)
        elif code == "prendas_vendidas":
            return self._top_productos(sv, limite_filas)
        elif code == "pedidos":
            return self._pedidos(sv, limite_filas)
        else:
            return self._ventas_por_sucursal(sv, limite_filas)

    def _obtener_ordenes_filtradas(self, sv: SpecValidada) -> list[OrderModel]:
        stmt = select(OrderModel).where(OrderModel.tenant_id == sv.tenant_id)
        if sv.spec.filters.status:
            stmt = stmt.where(OrderModel.status == sv.spec.filters.status)
        else:
            stmt = stmt.where(OrderModel.status.in_(["paid", "delivered", "shipped", "processing", "completed"]))

        if sv.branch_ids:
            stmt = stmt.where(OrderModel.branch_id.in_(sv.branch_ids))

        orders = self.db.scalars(stmt).all()

        # Filtrar por período en memoria para soportar SQLite y Postgres de forma consistente
        if sv.spec.filters.period:
            d_from = sv.spec.filters.period.date_from
            d_to = sv.spec.filters.period.date_to
            orders = [
                o for o in orders
                if o.created_at and d_from <= _to_date(o.created_at) <= d_to
            ]
        return orders

    def _obtener_mapa_categorias(self, tenant_id: uuid.UUID) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        categories_map = {
            str(cat.id): cat.name
            for cat in self.db.scalars(
                select(CategoryModel).where(CategoryModel.tenant_id == tenant_id)
            ).all()
        }
        variant_categories = {
            str(row[0]): row[1]
            for row in self.db.execute(
                select(ProductVariantModel.id, CategoryModel.name)
                .join(ProductModel, ProductModel.id == ProductVariantModel.product_id)
                .join(CategoryModel, CategoryModel.id == ProductModel.category_id)
                .where(ProductModel.tenant_id == tenant_id)
            ).all()
        }
        product_categories = {
            str(row[0]): row[1]
            for row in self.db.execute(
                select(ProductModel.id, CategoryModel.name)
                .join(CategoryModel, CategoryModel.id == ProductModel.category_id)
                .where(ProductModel.tenant_id == tenant_id)
            ).all()
        }
        return categories_map, variant_categories, product_categories

    def _resolver_categoria(self, item: dict, cat_map: dict, var_map: dict, prod_map: dict) -> str:
        return (
            item.get("category_name")
            or cat_map.get(str(item.get("category_id")))
            or var_map.get(str(item.get("variant_id")))
            or prod_map.get(str(item.get("product_id")))
            or item.get("category")
            or "General"
        )

    def _ventas_por_sucursal(self, sv: SpecValidada, limite: int) -> ReportResult:
        orders = self.obtener_ordenes = self._obtener_ordenes_filtradas(sv)
        branches = {b.id: b.name for b in self.db.scalars(select(BranchModel).where(BranchModel.tenant_id == sv.tenant_id)).all()}

        branch_stats: dict[uuid.UUID, dict[str, Any]] = defaultdict(lambda: {"revenue": Decimal(0), "orders": 0})
        for o in orders:
            b_id = o.branch_id
            branch_stats[b_id]["revenue"] += Decimal(str(o.total or 0))
            branch_stats[b_id]["orders"] += 1

        rows: list[dict[str, Any]] = []
        for b_id, stats in branch_stats.items():
            b_name = branches.get(b_id, f"Sucursal {str(b_id)[:8]}")
            rev = stats["revenue"]
            cnt = stats["orders"]
            avg = (rev / cnt) if cnt > 0 else Decimal(0)
            rows.append({
                "branch": b_name,
                "revenue": float(rev),
                "orders": cnt,
                "avg_ticket": round(float(avg), 2),
            })

        rows.sort(key=lambda r: r["revenue"], reverse=(sv.spec.order == "desc"))
        truncated = len(rows) > limite
        rows = rows[:limite]

        tot_rev = sum(r["revenue"] for r in rows)
        tot_ord = sum(r["orders"] for r in rows)
        tot_avg = round(tot_rev / tot_ord, 2) if tot_ord > 0 else 0.0

        columns = [
            {"key": "branch", "label": "Sucursal", "type": "text"},
            {"key": "revenue", "label": "Ventas (Bs)", "type": "money"},
            {"key": "orders", "label": "Pedidos", "type": "int"},
            {"key": "avg_ticket", "label": "Ticket Promedio (Bs)", "type": "money"},
        ]
        totals = {"branch": "TOTAL", "revenue": round(tot_rev, 2), "orders": tot_ord, "avg_ticket": tot_avg}

        chart_kind = elegir_grafico(sv.spec, len(rows))
        chart = {
            "kind": chart_kind.value,
            "x": "branch",
            "y": "revenue",
            "label": "Ingresos por sucursal (Bs)",
        }
        series = [{"name": "Ingresos", "data": [r["revenue"] for r in rows]}]

        return ReportResult(
            definition_code="ventas_por_sucursal",
            title="Ventas por sucursal",
            columns=columns,
            rows=rows,
            totals=totals,
            truncated=truncated,
            chart=chart,
            series=series,
        )

    def _top_productos(self, sv: SpecValidada, limite: int) -> ReportResult:
        orders = self._obtener_ordenes_filtradas(sv)
        limit_n = sv.spec.top_n or 10
        has_branch = Dimension.BRANCH in sv.spec.dimensions

        branches = {}
        if has_branch:
            branches = {
                b.id: b.name
                for b in self.db.scalars(
                    select(BranchModel).where(BranchModel.tenant_id == sv.tenant_id)
                ).all()
            }

        cat_map, var_map, prod_map = self._obtener_mapa_categorias(sv.tenant_id)
        norm_cats = {normalizar(c) for c in sv.spec.filters.category_names} if sv.spec.filters.category_names else None
        norm_prods = {normalizar(p) for p in sv.spec.filters.product_names} if sv.spec.filters.product_names else None

        prod_stats: dict[Any, dict[str, Any]] = defaultdict(
            lambda: {"units": 0, "revenue": Decimal(0), "sku": "", "branch": "", "product": ""}
        )

        for o in orders:
            b_name = branches.get(o.branch_id, f"Sucursal {str(o.branch_id)[:8]}") if has_branch else ""
            items = o.items or []
            for item in items:
                p_name = item.get("product_name") or item.get("name") or "Prenda sin nombre"
                cat_name = self._resolver_categoria(item, cat_map, var_map, prod_map)

                if norm_cats and normalizar(cat_name) not in norm_cats:
                    continue
                if norm_prods and normalizar(p_name) not in norm_prods:
                    continue

                qty = int(item.get("quantity") or 0)
                price = Decimal(str(item.get("unit_price") or item.get("price") or 0))
                line_total = Decimal(str(item.get("line_total") or (price * qty)))
                sku = item.get("sku") or ""

                key = (b_name, p_name) if has_branch else p_name
                stat = prod_stats[key]
                stat["units"] += qty
                stat["revenue"] += line_total
                stat["product"] = p_name
                if has_branch:
                    stat["branch"] = b_name
                if sku and not stat["sku"]:
                    stat["sku"] = sku

        rows: list[dict[str, Any]] = []
        for key, stats in prod_stats.items():
            row_data = {
                "product": stats["product"],
                "sku": stats["sku"] or "SKU-N/A",
                "units": stats["units"],
                "revenue": round(float(stats["revenue"]), 2),
            }
            if has_branch:
                row_data["branch"] = stats["branch"]
            rows.append(row_data)

        reverse_order = (sv.spec.order != "asc")
        if has_branch:
            by_branch: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for r in rows:
                by_branch[r["branch"]].append(r)

            top_rows: list[dict[str, Any]] = []
            for b_name in sorted(by_branch.keys()):
                b_rows = by_branch[b_name]
                b_rows.sort(key=lambda r: r["units"], reverse=reverse_order)
                top_rows.extend(b_rows[:limit_n])
            rows = top_rows
        else:
            rows.sort(key=lambda r: r["units"], reverse=reverse_order)
            rows = rows[:limit_n]

        tot_units = sum(r["units"] for r in rows)
        tot_rev = sum(r["revenue"] for r in rows)

        if has_branch:
            columns = [
                {"key": "branch", "label": "Sucursal", "type": "text"},
                {"key": "product", "label": "Producto", "type": "text"},
                {"key": "sku", "label": "SKU", "type": "text"},
                {"key": "units", "label": "Unidades vendidas", "type": "int"},
                {"key": "revenue", "label": "Total recaudado (Bs)", "type": "money"},
            ]
            totals = {"branch": "TOTAL", "product": "-", "sku": "-", "units": tot_units, "revenue": round(tot_rev, 2)}
            chart = {
                "kind": ChartKind.GROUPED_BAR.value,
                "x": "product",
                "group": "branch",
                "y": "units",
                "label": "Top productos más vendidos por sucursal",
            }
        else:
            columns = [
                {"key": "product", "label": "Producto", "type": "text"},
                {"key": "sku", "label": "SKU", "type": "text"},
                {"key": "units", "label": "Unidades vendidas", "type": "int"},
                {"key": "revenue", "label": "Total recaudado (Bs)", "type": "money"},
            ]
            totals = {"product": "TOTAL", "sku": "-", "units": tot_units, "revenue": round(tot_rev, 2)}
            chart_kind = elegir_grafico(sv.spec, len(rows))
            chart = {
                "kind": chart_kind.value,
                "x": "product",
                "y": "units",
                "label": "Top productos más vendidos",
            }

        series = [{"name": "Unidades", "data": [r["units"] for r in rows]}]

        return ReportResult(
            definition_code="top_productos",
            title="Top productos más vendidos" + (" por sucursal" if has_branch else ""),
            columns=columns,
            rows=rows,
            totals=totals,
            truncated=False,
            chart=chart,
            series=series,
        )

    def _pedidos(self, sv: SpecValidada, limite: int) -> ReportResult:
        orders = self._obtener_ordenes_filtradas(sv)
        status_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"orders": 0, "revenue": Decimal(0)})
        for o in orders:
            st = o.status or "sin_estado"
            status_stats[st]["orders"] += 1
            status_stats[st]["revenue"] += Decimal(str(o.total or 0))

        rows: list[dict[str, Any]] = []
        for st, data in status_stats.items():
            rows.append({
                "status": st.upper(),
                "orders": data["orders"],
                "revenue": round(float(data["revenue"]), 2),
            })

        rows.sort(key=lambda r: r["orders"], reverse=True)
        tot_orders = sum(r["orders"] for r in rows)
        tot_rev = sum(r["revenue"] for r in rows)

        columns = [
            {"key": "status", "label": "Estado del Pedido", "type": "text"},
            {"key": "orders", "label": "Cantidad de Pedidos", "type": "int"},
            {"key": "revenue", "label": "Monto Total (Bs)", "type": "money"},
        ]
        totals = {"status": "TOTAL", "orders": tot_orders, "revenue": round(tot_rev, 2)}
        chart = {"kind": ChartKind.BAR.value, "x": "status", "y": "orders", "label": "Pedidos por estado"}
        series = [{"name": "Pedidos", "data": [r["orders"] for r in rows]}]

        return ReportResult(
            definition_code="pedidos",
            title="Reporte de pedidos",
            columns=columns,
            rows=rows,
            totals=totals,
            truncated=False,
            chart=chart,
            series=series,
        )

    def _ventas_por_semana(self, sv: SpecValidada, limite: int) -> ReportResult:
        orders = self._obtener_ordenes_filtradas(sv)

        week_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"revenue": Decimal(0), "orders": 0, "date": None})
        for o in orders:
            dt = o.created_at if isinstance(o.created_at, datetime) else datetime.combine(o.created_at, datetime.min.time())
            year, week_num, _ = dt.isocalendar()
            week_key = f"{year}-W{week_num:02d}"
            week_stats[week_key]["revenue"] += Decimal(str(o.total or 0))
            week_stats[week_key]["orders"] += 1
            if not week_stats[week_key]["date"]:
                week_stats[week_key]["date"] = dt.strftime("%d/%m/%Y")

        sorted_keys = sorted(week_stats.keys())
        rows: list[dict[str, Any]] = []
        for k in sorted_keys:
            data = week_stats[k]
            rows.append({
                "week": k,
                "start_date": data["date"],
                "revenue": round(float(data["revenue"]), 2),
                "orders": data["orders"],
            })

        tot_rev = sum(r["revenue"] for r in rows)
        tot_ord = sum(r["orders"] for r in rows)

        columns = [
            {"key": "week", "label": "Semana", "type": "text"},
            {"key": "start_date", "label": "Fecha ref.", "type": "text"},
            {"key": "revenue", "label": "Ingresos (Bs)", "type": "money"},
            {"key": "orders", "label": "Pedidos", "type": "int"},
        ]
        totals = {"week": "TOTAL", "start_date": "-", "revenue": round(tot_rev, 2), "orders": tot_ord}

        chart = {
            "kind": ChartKind.LINE.value,
            "x": "week",
            "y": "revenue",
            "label": "Ventas semanales (Bs)",
        }
        series = [{"name": "Ingresos", "data": [r["revenue"] for r in rows]}]

        return ReportResult(
            definition_code="ventas_por_semana",
            title="Ventas por semana",
            columns=columns,
            rows=rows,
            totals=totals,
            truncated=False,
            chart=chart,
            series=series,
        )

    def _comparativa_sucursales(self, sv: SpecValidada, limite: int) -> ReportResult:
        orders = self._obtener_ordenes_filtradas(sv)
        branches = {b.id: b.name for b in self.db.scalars(select(BranchModel).where(BranchModel.tenant_id == sv.tenant_id)).all()}

        # Agrupar por sucursal y mes
        matrix: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        all_months: set[str] = set()

        for o in orders:
            b_name = branches.get(o.branch_id, f"Sucursal {str(o.branch_id)[:8]}")
            dt = o.created_at if isinstance(o.created_at, datetime) else datetime.combine(o.created_at, datetime.min.time())
            month_key = dt.strftime("%Y-%m")
            matrix[b_name][month_key] += Decimal(str(o.total or 0))
            all_months.add(month_key)

        sorted_months = sorted(all_months)
        rows: list[dict[str, Any]] = []

        for b_name, months_data in matrix.items():
            row: dict[str, Any] = {"branch": b_name}
            tot_branch = Decimal(0)
            for m in sorted_months:
                val = months_data.get(m, Decimal(0))
                row[m] = round(float(val), 2)
                tot_branch += val
            row["total"] = round(float(tot_branch), 2)
            rows.append(row)

        columns = [{"key": "branch", "label": "Sucursal", "type": "text"}]
        for m in sorted_months:
            columns.append({"key": m, "label": m, "type": "money"})
        columns.append({"key": "total", "label": "Total (Bs)", "type": "money"})

        totals: dict[str, Any] = {"branch": "TOTAL"}
        grand_total = 0.0
        for m in sorted_months:
            m_sum = sum(r.get(m, 0.0) for r in rows)
            totals[m] = round(m_sum, 2)
            grand_total += m_sum
        totals["total"] = round(grand_total, 2)

        series = []
        for m in sorted_months:
            series.append({
                "name": m,
                "data": [r.get(m, 0.0) for r in rows],
            })

        chart = {
            "kind": ChartKind.GROUPED_BAR.value,
            "x": "branch",
            "y": sorted_months[-1] if sorted_months else "total",
            "label": "Comparativa de sucursales",
        }

        return ReportResult(
            definition_code="comparativa_sucursales",
            title="Comparativa de sucursales",
            columns=columns,
            rows=rows,
            totals=totals,
            truncated=False,
            chart=chart,
            series=series,
        )

    def _menor_existencia(self, sv: SpecValidada, limite: int) -> ReportResult:
        threshold = sv.spec.filters.low_stock_lt or 10
        branches = {b.id: b.name for b in self.db.scalars(select(BranchModel).where(BranchModel.tenant_id == sv.tenant_id)).all()}

        stmt = (
            select(StockModel, ProductVariantModel, ProductModel)
            .join(ProductVariantModel, StockModel.variant_id == ProductVariantModel.id)
            .join(ProductModel, ProductVariantModel.product_id == ProductModel.id)
            .where(
                ProductModel.tenant_id == sv.tenant_id,
                StockModel.quantity <= threshold,
            )
        )
        if sv.branch_ids:
            stmt = stmt.where(StockModel.branch_id.in_(sv.branch_ids))

        results = self.db.execute(stmt).all()
        rows: list[dict[str, Any]] = []
        for stock, variant, prod in results:
            rows.append({
                "product": prod.name,
                "sku": variant.sku or "SKU-N/A",
                "branch": branches.get(stock.branch_id, "Sucursal"),
                "stock": stock.quantity,
            })

        rows.sort(key=lambda r: r["stock"])
        truncated = len(rows) > limite
        rows = rows[:limite]

        columns = [
            {"key": "product", "label": "Producto", "type": "text"},
            {"key": "sku", "label": "SKU", "type": "text"},
            {"key": "branch", "label": "Sucursal", "type": "text"},
            {"key": "stock", "label": "Stock actual", "type": "int"},
        ]
        totals = {"product": "TOTAL", "sku": "-", "branch": "-", "stock": sum(r["stock"] for r in rows)}

        chart = {
            "kind": ChartKind.TABLE.value,
            "x": "product",
            "y": "stock",
            "label": "Existencias críticas",
        }

        return ReportResult(
            definition_code="menor_existencia",
            title="Productos con menor existencia",
            columns=columns,
            rows=rows,
            totals=totals,
            truncated=truncated,
            chart=chart,
            series=[{"name": "Stock", "data": [r["stock"] for r in rows]}],
        )

    def _ingresos_por_categoria(self, sv: SpecValidada, limite: int) -> ReportResult:
        orders = self._obtener_ordenes_filtradas(sv)
        cat_map, var_map, prod_map = self._obtener_mapa_categorias(sv.tenant_id)
        cat_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"revenue": Decimal(0), "units": 0})

        for o in orders:
            items = o.items or []
            for item in items:
                cat_name = self._resolver_categoria(item, cat_map, var_map, prod_map)
                qty = int(item.get("quantity") or 0)
                price = Decimal(str(item.get("unit_price") or item.get("price") or 0))
                line_total = Decimal(str(item.get("line_total") or (price * qty)))

                cat_stats[cat_name]["units"] += qty
                cat_stats[cat_name]["revenue"] += line_total

        rows: list[dict[str, Any]] = []
        tot_rev = sum(s["revenue"] for s in cat_stats.values()) or Decimal(1)

        for cat, stats in cat_stats.items():
            rev = stats["revenue"]
            pct = round(float((rev / tot_rev) * 100), 1)
            rows.append({
                "category": cat,
                "revenue": round(float(rev), 2),
                "units": stats["units"],
                "percentage": pct,
            })

        rows.sort(key=lambda r: r["revenue"], reverse=True)
        totals = {
            "category": "TOTAL",
            "revenue": round(float(sum(r["revenue"] for r in rows)), 2),
            "units": sum(r["units"] for r in rows),
            "percentage": 100.0,
        }

        columns = [
            {"key": "category", "label": "Categoría", "type": "text"},
            {"key": "revenue", "label": "Ingresos (Bs)", "type": "money"},
            {"key": "units", "label": "Prendas vendidas", "type": "int"},
            {"key": "percentage", "label": "Participación (%)", "type": "pct"},
        ]

        chart = {
            "kind": ChartKind.PIE.value,
            "x": "category",
            "y": "revenue",
            "label": "Ingresos por categoría",
        }
        series = [{"name": "Ingresos", "data": [r["revenue"] for r in rows]}]

        return ReportResult(
            definition_code="ingresos_por_categoria",
            title="Ingresos por categoría",
            columns=columns,
            rows=rows,
            totals=totals,
            truncated=False,
            chart=chart,
            series=series,
        )

    def _pagos(self, sv: SpecValidada, limite: int) -> ReportResult:
        orders = self._obtener_ordenes_filtradas(sv)
        p_stats: dict[str, Decimal] = defaultdict(Decimal)
        for o in orders:
            method = o.payment_method or "desconocido"
            p_stats[method] += Decimal(str(o.total or 0))

        tot = sum(p_stats.values()) or Decimal(1)
        rows: list[dict[str, Any]] = []
        for m, rev in p_stats.items():
            rows.append({
                "payment_method": m.title(),
                "revenue": round(float(rev), 2),
                "percentage": round(float((rev / tot) * 100), 1),
            })

        columns = [
            {"key": "payment_method", "label": "Método de Pago", "type": "text"},
            {"key": "revenue", "label": "Total (Bs)", "type": "money"},
            {"key": "percentage", "label": "Porcentaje (%)", "type": "pct"},
        ]
        totals = {"payment_method": "TOTAL", "revenue": round(float(tot), 2), "percentage": 100.0}

        return ReportResult(
            definition_code="pagos",
            title="Reporte de formas de pago",
            columns=columns,
            rows=rows,
            totals=totals,
            truncated=False,
            chart={"kind": ChartKind.PIE.value, "x": "payment_method", "y": "revenue"},
            series=[{"name": "Ingresos", "data": [r["revenue"] for r in rows]}],
        )
