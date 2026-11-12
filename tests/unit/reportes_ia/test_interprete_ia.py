from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4
import pytest

from src.infrastructure.services.ai_client import AIService
from src.reportes_ia.application.interprete import Interprete
from src.reportes_ia.domain.especificacion import Dimension, Metric, ReportSpec


@pytest.fixture
def catalogo():
    return {
        "branches": [
            {"id": str(uuid4()), "name": "Sucursal Centro"},
            {"id": str(uuid4()), "name": "Sucursal Norte"},
        ],
        "categories": [
            {"id": str(uuid4()), "name": "Vestidos"},
            {"id": str(uuid4()), "name": "Faldas"},
        ],
        "products": [
            {"id": str(uuid4()), "name": "Vestido Aurora"},
            {"id": str(uuid4()), "name": "Camisa Lino"},
        ],
    }


def test_ia_devuelve_especificacion_examen(catalogo, monkeypatch):
    """IA devuelve la especificación del examen → READY, interpreter LLM, top_productos, PRODUCT+BRANCH, top_n 10."""
    respuesta_ia = (
        '{"status": "READY", "definition_code": "top_productos", "metrics": ["UNITS", "REVENUE"], '
        '"dimensions": ["PRODUCT", "BRANCH"], "top_n": 10, "order": "desc", '
        '"filters": {"period": {"date_from": "2026-08-14", "date_to": "2026-11-11", "label": "last_3_months"}}}'
    )
    monkeypatch.setattr(AIService, "is_configured", lambda self: True)
    monkeypatch.setattr(AIService, "generate", lambda self, prompt, **kw: respuesta_ia)

    inter = Interprete(catalogo)
    res = inter.interpretar("mostrar los 10 productos mas vendidos durante los ultimos 3 meses agrupados por sucursal")
    assert res.status == "READY"
    assert res.interpreter == "LLM"
    assert res.spec is not None
    assert res.spec.definition_code == "top_productos"
    assert Dimension.PRODUCT in res.spec.dimensions
    assert Dimension.BRANCH in res.spec.dimensions
    assert res.spec.top_n == 10


def test_ia_devuelve_definition_code_inexistente_cae_en_fallback(catalogo, monkeypatch):
    """IA devuelve definition_code inexistente → se descarta y responde el intérprete por reglas (FALLBACK)."""
    respuesta_ia = '{"status": "READY", "definition_code": "reporte_inventado_x", "metrics": ["UNITS"]}'
    monkeypatch.setattr(AIService, "is_configured", lambda self: True)
    monkeypatch.setattr(AIService, "generate", lambda self, prompt, **kw: respuesta_ia)

    inter = Interprete(catalogo)
    res = inter.interpretar("ventas por sucursal este mes")
    assert res.interpreter == "FALLBACK"
    assert res.spec is not None
    assert res.spec.definition_code == "ventas_por_sucursal"


def test_ia_devuelve_dimension_no_admitida_cae_en_fallback(catalogo, monkeypatch):
    """IA devuelve dimensión no admitida por el reporte → FALLBACK."""
    # ventas_por_semana no admite dimensión CATEGORY
    respuesta_ia = '{"status": "READY", "definition_code": "ventas_por_semana", "dimensions": ["CATEGORY"]}'
    monkeypatch.setattr(AIService, "is_configured", lambda self: True)
    monkeypatch.setattr(AIService, "generate", lambda self, prompt, **kw: respuesta_ia)

    inter = Interprete(catalogo)
    res = inter.interpretar("ventas por semana")
    assert res.interpreter == "FALLBACK"
    assert res.spec is not None
    assert res.spec.definition_code == "ventas_por_semana"


def test_ia_devuelve_needs_clarification(catalogo, monkeypatch):
    """IA devuelve {status: NEEDS_CLARIFICATION, questions:[…]} para «dame algo» → NEEDS_CLARIFICATION con la pregunta (5a)."""
    respuesta_ia = (
        '{"status": "NEEDS_CLARIFICATION", "questions": ["¿Qué querés ver: ventas o existencias?"], '
        '"suggestions": ["Ventas por sucursal", "Top productos"]}'
    )
    monkeypatch.setattr(AIService, "is_configured", lambda self: True)
    monkeypatch.setattr(AIService, "generate", lambda self, prompt, **kw: respuesta_ia)

    inter = Interprete(catalogo)
    res = inter.interpretar("dame algo")
    assert res.status == "NEEDS_CLARIFICATION"
    assert len(res.questions) > 0


def test_ia_devuelve_unsupported(catalogo, monkeypatch):
    """IA devuelve {status: UNSUPPORTED} → UNSUPPORTED con sugerencias (5b)."""
    respuesta_ia = '{"status": "UNSUPPORTED", "suggestions": ["Ventas por sucursal", "Top productos"]}'
    monkeypatch.setattr(AIService, "is_configured", lambda self: True)
    monkeypatch.setattr(AIService, "generate", lambda self, prompt, **kw: respuesta_ia)

    inter = Interprete(catalogo)
    res = inter.interpretar("pronóstico del clima en la tienda")
    assert res.status == "UNSUPPORTED"
    assert len(res.suggestions) > 0


def test_ia_lanza_timeout_cae_en_fallback_una_sola_llamada(catalogo, monkeypatch):
    """IA lanza tiempo agotado → FALLBACK y una sola llamada a AIService.generate."""
    calls = []

    def mock_gen(self, prompt, **kw):
        calls.append(prompt)
        raise TimeoutError("Deadline exceeded")

    monkeypatch.setattr(AIService, "is_configured", lambda self: True)
    monkeypatch.setattr(AIService, "generate", mock_gen)

    inter = Interprete(catalogo)
    res = inter.interpretar("ventas por sucursal")
    assert res.interpreter == "FALLBACK"
    assert res.spec is not None
    assert len(calls) == 1


def test_texto_con_verbo_escritura_sin_llamar_ia(catalogo, monkeypatch):
    """Texto con verbo de escritura → UNSUPPORTED sin llamar a la IA."""
    called = False

    def mock_gen(self, prompt, **kw):
        nonlocal called
        called = True
        return "{}"

    monkeypatch.setattr(AIService, "is_configured", lambda self: True)
    monkeypatch.setattr(AIService, "generate", mock_gen)

    inter = Interprete(catalogo)
    res = inter.interpretar("eliminar todas las órdenes de la semana")
    assert res.status == "UNSUPPORTED"
    assert not called


def test_reglas_prendas_vendidas_por_categoria(catalogo):
    """Reglas: «prendas vendidas por categoría este mes» → ingresos_por_categoria."""
    inter = Interprete(catalogo)
    res = inter.interpretar("prendas vendidas por categoría este mes")
    assert res.status == "READY"
    assert res.spec is not None
    assert res.spec.definition_code == "ingresos_por_categoria"


def test_reglas_productos_vendidos_por_semana(catalogo):
    """Reglas: «productos vendidos por semana» → ventas_por_semana."""
    inter = Interprete(catalogo)
    res = inter.interpretar("productos vendidos por semana")
    assert res.status == "READY"
    assert res.spec is not None
    assert res.spec.definition_code == "ventas_por_semana"


def test_reglas_top_5_en_sucursal_norte_como_filtro(catalogo):
    """Reglas: «top 5 productos más vendidos en Sucursal Norte» → top_productos, dimensions [PRODUCT], branch_names [Sucursal Norte]."""
    inter = Interprete(catalogo)
    res = inter.interpretar("top 5 productos más vendidos en Sucursal Norte")
    assert res.status == "READY"
    assert res.spec is not None
    assert res.spec.definition_code == "top_productos"
    assert res.spec.top_n == 5
    assert Dimension.PRODUCT in res.spec.dimensions
    assert Dimension.BRANCH not in res.spec.dimensions
    assert "Sucursal Norte" in res.spec.filters.branch_names


def test_reglas_consulta_literal_examen_top_productos_branch(catalogo):
    """Reglas: la consulta literal del examen sigue en top_productos con PRODUCT+BRANCH."""
    inter = Interprete(catalogo)
    res = inter.interpretar("mostrar los 10 productos mas vendidos durante los ultimos 3 meses agrupados por sucursal")
    assert res.status == "READY"
    assert res.spec is not None
    assert res.spec.definition_code == "top_productos"
    assert Dimension.PRODUCT in res.spec.dimensions
    assert Dimension.BRANCH in res.spec.dimensions
