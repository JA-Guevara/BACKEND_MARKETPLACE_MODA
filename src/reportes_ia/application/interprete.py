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
        ai = self.llm or AIService()
        ai_configured = False
        try:
            ai_configured = bool(ai.is_configured())
        except TypeError:
            ai_configured = bool(AIService.is_configured())

        if ai_configured:
            try:
                ai_res = self._interpretar_llm(texto, today, ai)
                if ai_res is not None:
                    return ai_res
            except Exception as exc:
                logger.warning("Fallo en interprete LLM, recurriendo al determinista: %s", exc)

        # En caso de no tener API key o fallar, pasamos al motor determinista garantizado
        return self._interpretar_determinista(texto, today)

    def _interpretar_llm(self, texto: str, today: date, ai: Any = None) -> Optional[InterpretResult]:
        ai_client = ai or self.llm or AIService()
        branches = [b["name"] for b in self.catalogo_empresa.get("branches", [])]
        categories = [c["name"] for c in self.catalogo_empresa.get("categories", [])]
        products = [p["name"] for p in self.catalogo_empresa.get("products", [])[:40]]

        prompt = f"""Eres el motor de interpretación semántica de reportes de FashionStore SaaS.
Fecha de referencia (hoy): {today.isoformat()}
Catálogo disponible en la empresa:
- Sucursales: {branches}
- Categorías: {categories}
- Productos ejemplo: {products}

Definiciones de reportes disponibles (definition_code):
- top_productos: Prendas más vendidas o con mayor recaudación. Dimensions: ["PRODUCT"] o ["PRODUCT", "BRANCH"] si se pide por sucursal. Metrics: ["UNITS", "REVENUE"].
- ventas_por_sucursal: Ventas por sucursal. Dimensions: ["BRANCH"]. Metrics: ["REVENUE", "ORDERS", "AVG_TICKET"].
- ventas_por_semana: Evolución cronológica semanal. Dimensions: ["WEEK"]. Metrics: ["REVENUE", "ORDERS"].
- comparativa_sucursales: Comparativa de tiendas. Dimensions: ["BRANCH", "MONTH"]. Metrics: ["REVENUE", "ORDERS"].
- menor_existencia: Stock bajo o crítico. Dimensions: ["PRODUCT", "BRANCH"]. Metrics: ["STOCK"].
- ingresos_por_categoria: Ingresos por categoría de prenda. Dimensions: ["CATEGORY"]. Metrics: ["REVENUE", "UNITS"].
- pagos: Métodos de pago. Dimensions: ["PAYMENT_METHOD"]. Metrics: ["REVENUE"].
- pedidos: Volumen de pedidos. Dimensions: ["STATUS"]. Metrics: ["ORDERS"].
- existencias: Inventario actual. Dimensions: ["PRODUCT", "BRANCH"]. Metrics: ["STOCK"].

Estructura de respuesta JSON:
1. Si la consulta es clara:
{{
  "status": "READY",
  "definition_code": "<codigo_valido>",
  "metrics": ["<METRICA>"],
  "dimensions": ["<DIMENSION>"],
  "top_n": null,
  "order": "desc",
  "compare_previous": false,
  "chart": "BAR" | "GROUPED_BAR" | "LINE" | "PIE" | "TABLE",
  "filters": {{
    "period": {{"date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD", "label": "..."}},
    "branch_names": [],
    "category_names": [],
    "product_names": [],
    "low_stock_lt": null
  }}
}}
2. Si la consulta es ambigua o incompleta:
{{"status": "NEEDS_CLARIFICATION", "questions": ["¿Qué querés ver: ventas o existencias?"], "suggestions": ["Ventas por sucursal", "Top productos"]}}
3. Si la consulta pide algo no soportado o ajeno:
{{"status": "UNSUPPORTED", "suggestions": ["Ventas por sucursal", "Top productos"]}}

Ejemplos:
- "mostrar los 10 productos mas vendidos durante los ultimos 3 meses agrupados por sucursal" -> status: READY, definition_code: "top_productos", dimensions: ["PRODUCT", "BRANCH"], metrics: ["UNITS", "REVENUE"], top_n: 10, chart: "GROUPED_BAR", filters.period con últimos 90 días.
- "ventas por semana" -> status: READY, definition_code: "ventas_por_semana", dimensions: ["WEEK"], metrics: ["REVENUE", "ORDERS"], chart: "LINE".
- "ingresos por categoría este mes" -> status: READY, definition_code: "ingresos_por_categoria", dimensions: ["CATEGORY"], metrics: ["REVENUE", "UNITS"], chart: "PIE".

Solicitud en lenguaje natural del usuario: "{texto}"
"""
        try:
            raw_json = ai_client.generate(
                prompt=prompt,
                system_instruction="Eres un extractor semántico estricto. Genera solo JSON válido.",
                json_mode=True,
                temperature=0.1,
                timeout=8,
            )
        except TypeError:
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

        status = data.get("status", "READY")
        if status == "NEEDS_CLARIFICATION":
            questions = data.get("questions") or ["¿Podrías especificar qué información deseas consultar?"]
            suggestions_list = data.get("suggestions") or [d.title for d in sugerencias(texto, 3)]
            return InterpretResult(
                status="NEEDS_CLARIFICATION",
                spec=None,
                questions=questions,
                assumptions=data.get("assumptions") or [],
                suggestions=suggestions_list,
                interpreter="LLM",
            )
        if status == "UNSUPPORTED":
            suggestions_list = data.get("suggestions") or [d.title for d in sugerencias(texto, 3)]
            return InterpretResult(
                status="UNSUPPORTED",
                spec=None,
                questions=[],
                assumptions=data.get("assumptions") or ["La consulta solicitada no está soportada."],
                suggestions=suggestions_list,
                interpreter="LLM",
            )

        # Validar definition_code contra REPORT_DEFINITIONS
        code = data.get("definition_code")
        if not code or code not in REPORT_DEFINITIONS:
            return None
        defn = REPORT_DEFINITIONS[code]

        # Normalizar enums a mayúsculas para compatibilidad con Pydantic
        if "metrics" in data and isinstance(data["metrics"], list):
            data["metrics"] = [m.upper() if isinstance(m, str) else m for m in data["metrics"]]
        else:
            data["metrics"] = list(defn.metrics)[:2]
        if "dimensions" in data and isinstance(data["dimensions"], list):
            data["dimensions"] = [d.upper() if isinstance(d, str) else d for d in data["dimensions"]]
        else:
            data["dimensions"] = list(defn.dimensions)
        if "chart" in data and isinstance(data["chart"], str):
            data["chart"] = data["chart"].upper()

        # Limpiar campos que no pertenecen a ReportSpec
        data.pop("status", None)
        data.pop("questions", None)
        data.pop("assumptions", None)
        data.pop("suggestions", None)
        data.pop("request_id", None)
        data.pop("interpreter", None)

        try:
            spec = ReportSpec.model_validate(data)
        except Exception as exc:
            logger.warning("Fallo al validar ReportSpec generado por LLM: %s", exc)
            return None

        # Validar compatibilidad contra la definición del reporte
        from src.reportes_ia.domain.catalogo import compatible
        errores = compatible(defn, spec)
        if errores:
            logger.warning("ReportSpec generado por LLM incompatible con %s: %s", code, errores)
            return None

        assumptions = ["«Últimos 3 meses» se tomó como los últimos 90 días."] if ("3 meses" in texto.lower() or "tres meses" in texto.lower()) else ["Interpretado mediante IA."]

        return InterpretResult(
            status="READY",
            spec=spec,
            questions=[],
            assumptions=assumptions,
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
            if re.search(r"\b(?:por|agrupados?\s+por)\s+(?:sucursal|tienda|sucursales|tiendas)\b", norm):
                dimensions = [Dimension.PRODUCT, Dimension.BRANCH]
                chart_kind = ChartKind.GROUPED_BAR
            else:
                dimensions = [Dimension.PRODUCT]

        if code == "top_productos":
            metrics_list = [Metric.UNITS, Metric.REVENUE]
        elif code in ("ventas_por_sucursal", "ventas"):
            metrics_list = [Metric.REVENUE, Metric.ORDERS]
        elif code == "ventas_por_semana":
            metrics_list = [Metric.REVENUE, Metric.ORDERS]
        elif code == "comparativa_sucursales":
            metrics_list = [Metric.REVENUE, Metric.ORDERS]
        elif code == "ingresos_por_categoria":
            metrics_list = [Metric.REVENUE, Metric.UNITS]
        elif code in ("menor_existencia", "existencias"):
            metrics_list = [Metric.STOCK]
        elif code == "pagos":
            metrics_list = [Metric.REVENUE]
        elif code == "pedidos":
            metrics_list = [Metric.ORDERS]
        else:
            metrics_list = [m for m in (Metric.REVENUE, Metric.UNITS, Metric.ORDERS, Metric.STOCK) if m in defn.metrics][:2] or [Metric.REVENUE]

        spec = ReportSpec(
            definition_code=code,
            metrics=metrics_list,
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
        # 1. Prioridad: por categoría (antes que vendidos general)
        if re.search(r"\bpor\s+categor[ií]a\b", norm) or "categoria" in norm or re.search(r"(?:ingreso|venta|recaudacion).*categoria", norm):
            return "ingresos_por_categoria"

        # 2. Prioridad: por semana (antes que vendidos general)
        if re.search(r"ventas?.*(?:por\s+semana|semanal)", norm) or re.search(r"\bpor\s+semana\b", norm) or "semanal" in norm or "semana" in norm:
            return "ventas_por_semana"

        # 3. top_productos (si menciona top o productos/prendas más vendidas)
        if (
            re.search(r"top.*(?:producto|prenda)", norm)
            or re.search(r"(?:diez|cinco|\d+)\s+productos\s+mas\s+vendidos", norm)
            or re.search(r"productos\s+mas\s+vendidos", norm)
            or re.search(r"prendas\s+mas\s+vendidas", norm)
            or re.search(r"\bproductos?\b.*\bvendidos?\b", norm)
            or re.search(r"\bprendas?\b.*\bvendidas?\b", norm)
        ):
            return "top_productos"

        # 4. comparativa_sucursales
        if re.search(r"compar.*(?:sucursal|tienda)", norm) or (
            "sucursal" in norm and ("tres meses" in norm or "3 meses" in norm or "meses" in norm)
        ):
            return "comparativa_sucursales"

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
