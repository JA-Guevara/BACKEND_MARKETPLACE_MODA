from datetime import date, datetime
import re
from typing import Any, Optional

from src.infrastructure.config.settings import settings
from src.reportes_ia.domain.catalogo import REPORT_DEFINITIONS, sugerencias
from src.reportes_ia.domain.especificacion import (
    ChartKind,
    Dimension,
    Filters,
    InterpretResult,
    Metric,
    Period,
    ReportSpec,
)
from src.reportes_ia.domain.grafico import periodo_por_defecto
from src.reportes_ia.domain.texto import extraer_periodo, nombrado, normalizar


RE_WRITING = re.compile(
    r"\b(borrar|eliminar|modificar|actualizar|insertar|crear|editar|cambiar|drop|delete|update|insert|truncate|alter)\b",
    re.IGNORECASE,
)
RE_CROSS_TENANT = re.compile(
    r"\b(otra empresa|todas las empresas|otro tenant|todos los tenants|otras tiendas)\b",
    re.IGNORECASE,
)
RE_SQL_LITERAL = re.compile(
    r"\b(select\s+\*|union\s+select|from\s+tenants|drop\s+table|exec\s+)\b",
    re.IGNORECASE,
)


class Interprete:
    def __init__(self, catalogo_empresa: dict[str, list[dict[str, Any]]], llm: Any | None = None) -> None:
        self.catalogo_empresa = catalogo_empresa
        self.llm = llm

    def interpretar(self, texto: str, hoy: date | None = None) -> InterpretResult:
        today = hoy or date.today()
        norm = normalizar(texto)

        # 1. Reglas 5b: verbos de escritura, otra empresa o SQL literal -> UNSUPPORTED
        if RE_WRITING.search(texto):
            return InterpretResult(
                status="UNSUPPORTED",
                spec=None,
                questions=[],
                assumptions=["No se admiten operaciones de escritura ni modificación de datos."],
                suggestions=[d.title for d in sugerencias(texto, 3)],
                interpreter="FALLBACK",
            )
        if RE_CROSS_TENANT.search(texto) or RE_SQL_LITERAL.search(texto):
            return InterpretResult(
                status="UNSUPPORTED",
                spec=None,
                questions=[],
                assumptions=["El análisis está estrictamente restringido a los datos de tu empresa."],
                suggestions=[d.title for d in sugerencias(texto, 3)],
                interpreter="FALLBACK",
            )

        # 2. Intentar LLM si está disponible (opcional)
        # En caso de no tener API key o fallar, pasamos al motor determinista garantizado
        return self._interpretar_determinista(texto, today)

    def _interpretar_determinista(self, texto: str, today: date) -> InterpretResult:
        norm = normalizar(texto)
        assumptions: list[str] = []
        questions: list[str] = []

        # Identificar periodo
        period_obj: Period | None = None
        try:
            period_dates, p_type = extraer_periodo(texto, today)
            if period_dates:
                d_from, d_to = period_dates
                period_obj = Period(date_from=d_from, date_to=d_to, label=p_type)
        except ValueError as exc:
            return InterpretResult(
                status="NEEDS_CLARIFICATION",
                spec=None,
                questions=[str(exc)],
                assumptions=[],
                suggestions=[d.title for d in sugerencias(texto, 3)],
                interpreter="FALLBACK",
            )

        # Sucursales detectadas
        branches_found: list[str] = []
        for b in self.catalogo_empresa.get("branches", []):
            if nombrado(b["name"], texto):
                branches_found.append(b["name"])

        # Categorías detectadas
        categories_found: list[str] = []
        for c in self.catalogo_empresa.get("categories", []):
            if nombrado(c["name"], texto):
                categories_found.append(c["name"])

        # Productos detectados
        products_found: list[str] = []
        for p in self.catalogo_empresa.get("products", []):
            if nombrado(p["name"], texto):
                products_found.append(p["name"])

        # Identificar definición de reporte
        code = self._identificar_definicion(norm)

        # Si no se identificó nada claro
        if not code:
            sugs = sugerencias(texto, 3)
            return InterpretResult(
                status="UNSUPPORTED",
                spec=None,
                questions=[],
                assumptions=["No se identificó un tipo de reporte admitido en la consulta."],
                suggestions=[d.title for d in sugs],
                interpreter="FALLBACK",
            )

        defn = REPORT_DEFINITIONS[code]

        # Si la definición requiere período y no vino en la consulta
        if "period" in defn.filters and not period_obj:
            period_obj = periodo_por_defecto(today)
            assumptions.append("Se usó el mes en curso al no especificar fechas.")

        # top_n
        top_n: int | None = None
        match_top = re.search(r"\b(?:top|los|primeros|mejores)\s+(\d+|diez|cinco|tres|veinte)\b", norm)
        if match_top:
            val_token = match_top.group(1)
            num_map = {"diez": 10, "cinco": 5, "tres": 3, "veinte": 20}
            top_n = int(val_token) if val_token.isdigit() else num_map.get(val_token, 10)
        elif code == "top_productos":
            top_n = 10

        # Umbral stock bajo
        low_stock_lt: int | None = None
        match_stock = re.search(r"(?:menor|debajo|inferior|<)\s*(?:a|de)?\s*(\d+)", norm)
        if match_stock:
            low_stock_lt = int(match_stock.group(1))
        elif code == "menor_existencia":
            low_stock_lt = 10

        # Comparar con previo
        compare_previous = bool(re.search(r"\b(comparar|comparativa|vs|frente al|respecto al)\b", norm))

        filters = Filters(
            period=period_obj,
            branch_names=branches_found,
            category_names=categories_found,
            product_names=products_found,
            low_stock_lt=low_stock_lt,
        )

        spec = ReportSpec(
            definition_code=code,
            metrics=list(defn.metrics)[:2] or [Metric.REVENUE],
            dimensions=list(defn.dimensions),
            filters=filters,
            top_n=top_n,
            order="desc" if code != "menor_existencia" else "asc",
            compare_previous=compare_previous,
            chart=defn.default_chart,
        )

        return InterpretResult(
            status="READY",
            spec=spec,
            questions=questions,
            assumptions=assumptions,
            suggestions=[],
            interpreter="FALLBACK",
        )

    def _identificar_definicion(self, norm: str) -> Optional[str]:
        # 1. comparativa_sucursales
        if re.search(r"compar.*(?:sucursal|tienda)", norm) or (
            "sucursal" in norm and ("tres meses" in norm or "3 meses" in norm or "meses" in norm)
        ):
            return "comparativa_sucursales"

        # 2. top_productos
        if (
            re.search(r"top.*(?:producto|prenda)", norm)
            or re.search(r"(?:diez|cinco|\d+)\s+productos\s+mas\s+vendidos", norm)
            or re.search(r"productos\s+mas\s+vendidos", norm)
            or re.search(r"prendas\s+mas\s+vendidas", norm)
        ):
            return "top_productos"

        # 3. ventas_por_semana
        if re.search(r"ventas?.*(?:por\s+semana|semanal)", norm) or "semana" in norm:
            return "ventas_por_semana"

        # 4. ingresos_por_categoria
        if re.search(r"(?:ingreso|venta|recaudacion).*categoria", norm) or "categoria" in norm:
            return "ingresos_por_categoria"

        # 5. menor_existencia
        if (
            re.search(r"menor\s+existencia", norm)
            or re.search(r"bajo\s+stock", norm)
            or re.search(r"stock\s+critico", norm)
            or re.search(r"menor\s+stock", norm)
        ):
            return "menor_existencia"

        # 6. ventas_por_sucursal
        if re.search(r"ventas?.*(?:por\s+sucursal|por\s+tienda|agrupadas\s+por\s+sucursal)", norm) or (
            "sucursal" in norm and "venta" in norm
        ):
            return "ventas_por_sucursal"

        # Formas de pago
        if re.search(r"forma.*pago|metodo.*pago|efectivo|tarjeta", norm):
            return "pagos"

        # Existencias general
        if re.search(r"existencias?|inventario", norm):
            return "existencias"

        # Pedidos
        if re.search(r"pedidos?", norm):
            return "pedidos"

        # Sucursales general
        if re.search(r"sucursales|tiendas", norm):
            return "ventas_por_sucursal"

        # Ventas general
        if re.search(r"ventas?", norm):
            return "ventas"

        return None
