from dataclasses import dataclass
from typing import Optional
from src.reportes_ia.domain.especificacion import ChartKind, Dimension, Metric, ReportSpec
from src.reportes_ia.domain.texto import normalizar


@dataclass(frozen=True)
class ReportDefinition:
    code: str
    title: str
    description: str
    metrics: frozenset[Metric]
    dimensions: frozenset[Dimension]
    filters: frozenset[str]
    default_chart: ChartKind
    max_rows: int
    examples: tuple[str, ...]


REPORT_DEFINITIONS: dict[str, ReportDefinition] = {
    # 6 Reportes de CU-09 (enunciado 8.2)
    "ventas_por_sucursal": ReportDefinition(
        code="ventas_por_sucursal",
        title="Ventas por sucursal",
        description="Ingresos y pedidos agrupados por sucursal física o virtual.",
        metrics=frozenset({Metric.REVENUE, Metric.ORDERS, Metric.AVG_TICKET}),
        dimensions=frozenset({Dimension.BRANCH}),
        filters=frozenset({"period", "branch_names", "status"}),
        default_chart=ChartKind.BAR,
        max_rows=100,
        examples=(
            "Mostrame las ventas de septiembre agrupadas por sucursal",
            "Ventas por sucursal este mes",
            "Ingresos de cada tienda en el periodo",
        ),
    ),
    "top_productos": ReportDefinition(
        code="top_productos",
        title="Top productos más vendidos",
        description="Prendas con mayor cantidad vendida o recaudación.",
        metrics=frozenset({Metric.UNITS, Metric.REVENUE}),
        dimensions=frozenset({Dimension.PRODUCT}),
        filters=frozenset({"period", "branch_names", "category_names", "product_names"}),
        default_chart=ChartKind.BAR,
        max_rows=50,
        examples=(
            "¿Cuáles fueron los diez productos más vendidos este mes?",
            "Top 10 productos más vendidos",
            "Prendas más vendidas del periodo",
        ),
    ),
    "ventas_por_semana": ReportDefinition(
        code="ventas_por_semana",
        title="Ventas por semana",
        description="Evolución cronológica de ventas agrupadas por semana.",
        metrics=frozenset({Metric.REVENUE, Metric.ORDERS}),
        dimensions=frozenset({Dimension.WEEK}),
        filters=frozenset({"period", "branch_names", "status"}),
        default_chart=ChartKind.LINE,
        max_rows=150,
        examples=(
            "Generá un gráfico de ventas por semana",
            "Ventas por semana del trimestre",
            "Evolución semanal de ingresos",
        ),
    ),
    "comparativa_sucursales": ReportDefinition(
        code="comparativa_sucursales",
        title="Comparativa de sucursales",
        description="Comparación de ventas entre sucursales a lo largo de los meses.",
        metrics=frozenset({Metric.REVENUE, Metric.ORDERS}),
        dimensions=frozenset({Dimension.BRANCH, Dimension.MONTH}),
        filters=frozenset({"period", "branch_names"}),
        default_chart=ChartKind.GROUPED_BAR,
        max_rows=200,
        examples=(
            "Compará las ventas de las sucursales durante los últimos tres meses",
            "Comparativa mensual de tiendas",
            "Ventas de sucursales mes a mes",
        ),
    ),
    "menor_existencia": ReportDefinition(
        code="menor_existencia",
        title="Productos con menor existencia",
        description="Prendas y variantes con inventario crítico o por agotarse.",
        metrics=frozenset({Metric.STOCK}),
        dimensions=frozenset({Dimension.PRODUCT, Dimension.BRANCH}),
        filters=frozenset({"branch_names", "category_names", "low_stock_lt"}),
        default_chart=ChartKind.TABLE,
        max_rows=200,
        examples=(
            "Mostrame los productos con menor existencia",
            "Stock crítico por debajo de 5 unidades",
            "Prendas con inventario bajo",
        ),
    ),
    "ingresos_por_categoria": ReportDefinition(
        code="ingresos_por_categoria",
        title="Ingresos por categoría",
        description="Distribución y participación porcentual de ingresos por categoría de prendas.",
        metrics=frozenset({Metric.REVENUE, Metric.UNITS}),
        dimensions=frozenset({Dimension.CATEGORY}),
        filters=frozenset({"period", "branch_names", "category_names"}),
        default_chart=ChartKind.PIE,
        max_rows=50,
        examples=(
            "¿Qué categorías generaron mayores ingresos durante este período?",
            "Ingresos por categoría este mes",
            "Ventas desglosadas por categoría",
        ),
    ),

    # 6 Reportes existentes (primer parcial)
    "ventas": ReportDefinition(
        code="ventas",
        title="Reporte de ventas",
        description="Histórico detallado y agregado de ventas.",
        metrics=frozenset({Metric.REVENUE, Metric.ORDERS, Metric.AVG_TICKET}),
        dimensions=frozenset({Dimension.DAY, Dimension.MONTH}),
        filters=frozenset({"period", "branch_names", "status"}),
        default_chart=ChartKind.LINE,
        max_rows=500,
        examples=("Ventas generales", "Reporte de ventas diario"),
    ),
    "pedidos": ReportDefinition(
        code="pedidos",
        title="Reporte de pedidos",
        description="Volumen y estado de pedidos realizados.",
        metrics=frozenset({Metric.ORDERS}),
        dimensions=frozenset({Dimension.STATUS, Dimension.DAY}),
        filters=frozenset({"period", "branch_names", "status"}),
        default_chart=ChartKind.BAR,
        max_rows=500,
        examples=("Reporte de pedidos", "Pedidos por estado"),
    ),
    "pagos": ReportDefinition(
        code="pagos",
        title="Reporte de formas de pago",
        description="Distribución de transacciones por método de pago.",
        metrics=frozenset({Metric.REVENUE}),
        dimensions=frozenset({Dimension.PAYMENT_METHOD}),
        filters=frozenset({"period", "branch_names"}),
        default_chart=ChartKind.PIE,
        max_rows=50,
        examples=("Ventas por método de pago", "Pagos en efectivo vs tarjeta"),
    ),
    "prendas_vendidas": ReportDefinition(
        code="prendas_vendidas",
        title="Prendas vendidas",
        description="Unidades físicas vendidas por producto y categoría.",
        metrics=frozenset({Metric.UNITS, Metric.REVENUE}),
        dimensions=frozenset({Dimension.PRODUCT, Dimension.CATEGORY}),
        filters=frozenset({"period", "branch_names", "category_names"}),
        default_chart=ChartKind.BAR,
        max_rows=300,
        examples=("Prendas vendidas en el periodo", "Unidades vendidas"),
    ),
    "existencias": ReportDefinition(
        code="existencias",
        title="Inventario de existencias",
        description="Stock actual por sucursal y producto.",
        metrics=frozenset({Metric.STOCK}),
        dimensions=frozenset({Dimension.PRODUCT, Dimension.BRANCH}),
        filters=frozenset({"branch_names", "category_names", "low_stock_lt"}),
        default_chart=ChartKind.TABLE,
        max_rows=500,
        examples=("Reporte de existencias", "Inventario general"),
    ),
    "sucursales": ReportDefinition(
        code="sucursales",
        title="Rendimiento de sucursales",
        description="Métricas consolidadas de cada sucursal.",
        metrics=frozenset({Metric.REVENUE, Metric.ORDERS}),
        dimensions=frozenset({Dimension.BRANCH}),
        filters=frozenset({"period", "branch_names"}),
        default_chart=ChartKind.BAR,
        max_rows=100,
        examples=("Rendimiento de tiendas", "Consolidado por sucursal"),
    ),
}


def obtener_definicion(code: str) -> Optional[ReportDefinition]:
    return REPORT_DEFINITIONS.get(code)


def compatible(defn: ReportDefinition, spec: ReportSpec) -> list[str]:
    errores: list[str] = []
    for m in spec.metrics:
        if m not in defn.metrics:
            errores.append(f"Métrica '{m}' no es admitida por el reporte '{defn.code}'.")
    for d in spec.dimensions:
        if d not in defn.dimensions:
            errores.append(f"Dimensión '{d}' no es admitida por el reporte '{defn.code}'.")
    return errores


def sugerencias(texto_normalizado: str, n: int = 3) -> list[ReportDefinition]:
    texto = normalizar(texto_normalizado)
    ranking: list[tuple[int, ReportDefinition]] = []
    for defn in REPORT_DEFINITIONS.values():
        puntos = 0
        palabras_clave = (defn.title + " " + defn.description + " " + " ".join(defn.examples)).lower()
        for token in set(texto.split()):
            if len(token) > 3 and token in palabras_clave:
                puntos += 1
        ranking.append((puntos, defn))
    ranking.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in ranking[:n]]
