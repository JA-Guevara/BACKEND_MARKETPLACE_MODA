from datetime import date, datetime
import json
import logging
import re
from typing import Any, Optional

from src.infrastructure.config.settings import settings
from src.infrastructure.services.ai_client import AIService
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

logger = logging.getLogger(__name__)


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

        # 2. Intentar LLM si está disponible (AIService con Gemini o compatible)
        if AIService.is_configured():
            try:
                ai_res = self._interpretar_llm(texto, today)
                if ai_res and ai_res.status == "READY":
                    return ai_res
            except Exception as exc:
                logger.warning("Fallo en interprete LLM, recurriendo al determinista: %s", exc)

        # En caso de no tener API key o fallar, pasamos al motor determinista garantizado
        return self._interpretar_determinista(texto, today)

    def _interpretar_llm(self, texto: str, today: date) -> Optional[InterpretResult]:
        branches = [b["name"] for b in self.catalogo_empresa.get("branches", [])]
        categories = [c["name"] for c in self.catalogo_empresa.get("categories", [])]
        products = [p["name"] for p in self.catalogo_empresa.get("products", [])[:40]]

        prompt = f"""Eres el motor de interpretación de reportes empresariales de FashionStore SaaS.
Fecha de referencia (hoy): {today.isoformat()}
Catálogo disponible en la empresa:
- Sucursales: {branches}
- Categorías: {categories}
- Productos ejemplo: {products}

Reportes disponibles (definition_code):
- top_productos: Prendas más vendidas o con mayor recaudación. Dimensions: ["product"] o ["product", "branch"] si se pide por sucursal. Metrics: ["units", "revenue"].
- ventas_por_sucursal: Ventas por sucursal. Dimensions: ["branch"]. Metrics: ["revenue", "orders", "avg_ticket"].
- ventas_por_semana: Evolución semanal. Dimensions: ["week"]. Metrics: ["revenue", "orders"].
- comparativa_sucursales: Comparativa de tiendas mes a mes. Dimensions: ["branch", "month"]. Metrics: ["revenue", "orders"].
- menor_existencia: Stock bajo o crítico. Dimensions: ["product", "branch"]. Metrics: ["stock"].
- ingresos_por_categoria: Ingresos por categoría. Dimensions: ["category"]. Metrics: ["revenue", "units"].
- pagos: Métodos de pago. Dimensions: ["payment_method"]. Metrics: ["revenue"].
- pedidos: Volumen de pedidos. Dimensions: ["status"]. Metrics: ["orders"].
- existencias: Inventario actual. Dimensions: ["product", "branch"]. Metrics: ["stock"].

Solicitud en lenguaje natural del usuario: "{texto}"

REGLA CLAVE: Si el usuario pide "productos mas vendidos", "prendas mas vendidas", o "top productos", definition_code DEBE ser "top_productos". Si además pide "agrupados por sucursal" o "por sucursal", dimensions DEBE ser ["product", "branch"] y chart "grouped_bar".
REGLA DE FECHAS: "ultimos 3 meses" equivale a fecha_desde = (hoy - 90 días) y fecha_hasta = hoy.

Genera ÚNICAMENTE un JSON con esta estructura exacta (sin markdown extra):
{{
  "definition_code": "top_productos",
  "metrics": ["units", "revenue"],
  "dimensions": ["product", "branch"],
  "top_n": 10,
  "order": "desc",
  "compare_previous": false,
  "chart": "grouped_bar",
  "filters": {{
    "period": {{
      "date_from": "YYYY-MM-DD",
      "date_to": "YYYY-MM-DD",
      "label": "last_period"
    }},
    "branch_names": [],
    "category_names": [],
    "product_names": [],
    "low_stock_lt": null
  }}
}}
"""
        raw_json = AIService.generate(
            prompt=prompt,
            system_instruction="Eres un extractor semántico estricto. Genera solo JSON válido.",
            json_mode=True,
            temperature=0.1,
            timeout=8,
        )
        if not raw_json:
            return None
        clean_json = raw_json.strip()
        if clean_json.startswith("```"):
            clean_json = clean_json.split("\n", 1)[1]
            if clean_json.endswith("```"):
                clean_json = clean_json.rsplit("```", 1)[0].strip()
        data = json.loads(clean_json)
        # Normalizar enums a mayúsculas para compatibilidad con Pydantic
        if "metrics" in data and isinstance(data["metrics"], list):
            data["metrics"] = [m.upper() if isinstance(m, str) else m for m in data["metrics"]]
        if "dimensions" in data and isinstance(data["dimensions"], list):
            data["dimensions"] = [d.upper() if isinstance(d, str) else d for d in data["dimensions"]]
        if "chart" in data and isinstance(data["chart"], str):
            data["chart"] = data["chart"].upper()

        spec = ReportSpec.model_validate(data)
        return InterpretResult(
            status="READY",
            spec=spec,
            questions=[],
            assumptions=["Interpretado mediante Gemini AI."],
            suggestions=[],
            interpreter="LLM",
        )

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

        # Dimensiones y gráfico
        dimensions = list(defn.dimensions)
        chart_kind = defn.default_chart
        if code == "top_productos":
            if re.search(r"\b(?:por|agrupados?\s+por)\s+(?:sucursal|tienda|sucursales|tiendas)\b", norm) or "sucursal" in norm:
                dimensions = [Dimension.PRODUCT, Dimension.BRANCH]
                chart_kind = ChartKind.GROUPED_BAR
            else:
                dimensions = [Dimension.PRODUCT]

        spec = ReportSpec(
            definition_code=code,
            metrics=list(defn.metrics)[:2] or [Metric.REVENUE],
            dimensions=dimensions,
            filters=filters,
            top_n=top_n,
            order="desc" if code != "menor_existencia" else "asc",
            compare_previous=compare_previous,
            chart=chart_kind,
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
        # 1. top_productos (prioridad máxima si menciona top o productos/prendas más vendidas)
        if (
            re.search(r"top.*(?:producto|prenda)", norm)
            or re.search(r"(?:diez|cinco|\d+)\s+productos\s+mas\s+vendidos", norm)
            or re.search(r"productos\s+mas\s+vendidos", norm)
            or re.search(r"prendas\s+mas\s+vendidas", norm)
            or re.search(r"\bproductos?\b.*\bvendidos?\b", norm)
            or re.search(r"\bprendas?\b.*\bvendidas?\b", norm)
        ):
            return "top_productos"

        # 2. comparativa_sucursales
        if re.search(r"compar.*(?:sucursal|tienda)", norm) or (
            "sucursal" in norm and ("tres meses" in norm or "3 meses" in norm or "meses" in norm)
        ):
            return "comparativa_sucursales"

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
