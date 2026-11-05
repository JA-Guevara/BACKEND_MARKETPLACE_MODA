from datetime import date
import pytest
from pydantic import ValidationError

from src.reportes_ia.domain.catalogo import REPORT_DEFINITIONS, compatible, sugerencias
from src.reportes_ia.domain.especificacion import (
    ChartKind,
    Dimension,
    Filters,
    Metric,
    Period,
    ReportSpec,
)
from src.reportes_ia.domain.grafico import elegir_grafico, periodo_por_defecto


def test_periodo_validacion_rango_y_maximo():
    # Rango válido
    p = Period(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30), label="Septiembre")
    assert p.date_from == date(2026, 9, 1)

    # Invertido falla
    with pytest.raises(ValidationError):
        Period(date_from=date(2026, 10, 1), date_to=date(2026, 9, 1))

    # Más de 24 meses falla
    with pytest.raises(ValidationError):
        Period(date_from=date(2020, 1, 1), date_to=date(2026, 1, 1))


def test_report_spec_inmutabilidad_y_extra_forbid():
    with pytest.raises(ValidationError):
        # extra="forbid" rechaza campos no autorizados (como SQL o tenant_id)
        ReportSpec(
            definition_code="ventas_por_sucursal",
            metrics=[Metric.REVENUE],
            sql_query="SELECT * FROM users",  # Campo no permitido
        )


def test_catalogo_contiene_los_seis_reportes_del_enunciado():
    esperados = [
        "ventas_por_sucursal",
        "top_productos",
        "ventas_por_semana",
        "comparativa_sucursales",
        "menor_existencia",
        "ingresos_por_categoria",
    ]
    for code in esperados:
        assert code in REPORT_DEFINITIONS
        defn = REPORT_DEFINITIONS[code]
        assert len(defn.examples) >= 1
        assert defn.max_rows > 0


def test_compatibilidad_definicion_spec():
    defn = REPORT_DEFINITIONS["ventas_por_sucursal"]
    # Válido
    spec_valida = ReportSpec(
        definition_code="ventas_por_sucursal",
        metrics=[Metric.REVENUE],
        dimensions=[Dimension.BRANCH],
    )
    assert compatible(defn, spec_valida) == []

    # Incompatible: métrica STOCK no admitida en ventas_por_sucursal
    spec_invalida = ReportSpec(
        definition_code="ventas_por_sucursal",
        metrics=[Metric.STOCK],
        dimensions=[Dimension.BRANCH],
    )
    errores = compatible(defn, spec_invalida)
    assert len(errores) == 1
    assert "Métrica" in errores[0]


def test_elegir_grafico_reglas_heuristicas():
    # Temporal -> LINE
    spec_line = ReportSpec(
        definition_code="ventas_por_semana",
        metrics=[Metric.REVENUE],
        dimensions=[Dimension.WEEK],
    )
    assert elegir_grafico(spec_line) == ChartKind.LINE

    # 2 dimensiones -> GROUPED_BAR
    spec_grouped = ReportSpec(
        definition_code="comparativa_sucursales",
        metrics=[Metric.REVENUE],
        dimensions=[Dimension.BRANCH, Dimension.MONTH],
    )
    assert elegir_grafico(spec_grouped) == ChartKind.GROUPED_BAR

    # Categoría con pocas filas -> PIE
    spec_pie = ReportSpec(
        definition_code="ingresos_por_categoria",
        metrics=[Metric.REVENUE],
        dimensions=[Dimension.CATEGORY],
    )
    assert elegir_grafico(spec_pie, n_filas=4) == ChartKind.PIE

    # Demasiadas filas -> TABLE
    assert elegir_grafico(spec_pie, n_filas=30) == ChartKind.TABLE


def test_sugerencias_por_texto():
    sugs = sugerencias("quisiera ver cuanto vendio cada tienda o sucursal", n=2)
    assert len(sugs) >= 1
    codes = [s.code for s in sugs]
    assert "ventas_por_sucursal" in codes or "sucursales" in codes
