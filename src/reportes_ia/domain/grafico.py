from datetime import date
from src.reportes_ia.domain.especificacion import ChartKind, Dimension, Period, ReportSpec


def elegir_grafico(spec: ReportSpec, n_filas: int = 0, n_series: int = 1) -> ChartKind:
    if spec.chart:
        return spec.chart

    # Si hay 2 dimensiones o series múltiples
    if len(spec.dimensions) >= 2 or n_series > 1:
        return ChartKind.GROUPED_BAR

    # Si la dimensión es temporal (DAY, WEEK, MONTH)
    if any(d in (Dimension.DAY, Dimension.WEEK, Dimension.MONTH) for d in spec.dimensions):
        return ChartKind.LINE

    # Participación por categoría o forma de pago con pocas filas
    if any(d in (Dimension.CATEGORY, Dimension.PAYMENT_METHOD) for d in spec.dimensions) and n_filas <= 6:
        return ChartKind.PIE

    # Si hay demasiadas filas para un gráfico de barras legible
    if n_filas > 25:
        return ChartKind.TABLE

    return ChartKind.BAR


def periodo_por_defecto(hoy: date | None = None) -> Period:
    today = hoy or date.today()
    inicio_mes = today.replace(day=1)
    return Period(
        date_from=inicio_mes,
        date_to=today,
        label="Mes en curso",
    )
