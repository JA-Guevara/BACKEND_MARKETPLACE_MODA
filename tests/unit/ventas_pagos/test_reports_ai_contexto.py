"""QA del asistente de reportes (Funcion A): el contexto visible del dashboard
que llega por ``current`` ahora se usa como punto de partida para pedidos como
"explicame esto", y lo que el texto pide explícitamente gana después."""
from datetime import datetime, timezone
from uuid import uuid4

from src.ventas_pagos.application.reports_ai import ReportsAI
from src.ventas_pagos.web.schemas import ReportFilters

B_CENTRAL = uuid4()
C_CAMISAS = uuid4()


def _catalog():
    return {
        "branches": [{"id": str(B_CENTRAL), "name": "Sucursal Central"}],
        "categories": [{"id": str(C_CAMISAS), "name": "Camisas"}],
    }


def _current(**kw) -> ReportFilters:
    defaults = dict(
        date_from=datetime(2026, 8, 1, 4, 0, tzinfo=timezone.utc),
        date_to=datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc),
        branch_id=None,
        category_id=None,
        status=None,
    )
    defaults.update(kw)
    return ReportFilters(**defaults)


def test_pedido_referido_usa_el_contexto_visible():
    ai = ReportsAI(None)
    current = _current(branch_id=B_CENTRAL, category_id=C_CAMISAS)
    result = ai.interpret("explicame esto", current, _catalog())
    assert result["filtros"]["branch_id"] == str(B_CENTRAL)
    assert result["filtros"]["category_id"] == str(C_CAMISAS)
    assert result["filtros"]["date_from"].startswith("2026-08-01")
    assert result["filtros"]["date_to"].startswith("2026-09-01")
    assert any("visibles del dashboard" in a for a in result["aclaraciones"])


def test_periodo_explicito_gana_al_contexto():
    ai = ReportsAI(None)
    current = _current(date_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
                       date_to=datetime(2025, 2, 1, tzinfo=timezone.utc))
    result = ai.interpret("de esto, ventas del último mes", current, _catalog())
    # El periodo pedido en el texto reemplaza al del contexto visible.
    assert result["filtros"]["date_from"].startswith("2026")
    assert result["filtros"]["branch_id"] is None


def test_sucursal_nombrada_gana_al_contexto():
    norte = uuid4()
    catalog = {
        "branches": [{"id": str(norte), "name": "Sucursal Norte"}],
        "categories": [],
    }
    ai = ReportsAI(None)
    current = _current(branch_id=B_CENTRAL)
    result = ai.interpret("muestrame esto de la sucursal norte", current, catalog)
    assert result["filtros"]["branch_id"] == str(norte)


def test_sin_referencia_al_contexto_no_se_siembra():
    ai = ReportsAI(None)
    current = _current(branch_id=B_CENTRAL)
    result = ai.interpret("ventas por sucursal", current, _catalog())
    # "por sucursal" es agrupación, no filtra la sucursal visible.
    assert result["filtros"]["branch_id"] is None
    assert result["agrupacion"] == "sucursal"