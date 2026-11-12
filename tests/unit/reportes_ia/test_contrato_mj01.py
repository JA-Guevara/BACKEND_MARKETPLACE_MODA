import json
from pathlib import Path
import pytest

from src.reportes_ia.domain.especificacion import InterpretResult
from src.reportes_ia.web.schemas import InterpretIn, ReportResponse, RunIn
from src.operacion_offline.web.sync_schemas import ConflictOut, ConflictResolveIn


FIXTURES_DIR = Path(__file__).resolve().parents[4] / "docs" / "MJ-01-reportes-ia-conflictos" / "contrato" / "fixtures"


def _cargar_fixture(nombre: str) -> dict:
    archivo = FIXTURES_DIR / nombre
    if not archivo.exists():
        # Fallback si se corre desde otro directorio
        alt = Path("docs/MJ-01-reportes-ia-conflictos/contrato/fixtures") / nombre
        if alt.exists():
            archivo = alt
    assert archivo.exists(), f"No se encontró el fixture {nombre} en {archivo}"
    return json.loads(archivo.read_text(encoding="utf-8"))


def test_fixture_interpret_peticion_examen():
    data = _cargar_fixture("interpret_peticion_examen.json")
    obj = InterpretIn.model_validate(data)
    assert obj.text == data["text"]
    assert obj.channel == "TEXT"


def test_fixture_interpret_examen():
    data = _cargar_fixture("interpret_examen.json")
    obj = InterpretResult.model_validate(data)
    assert obj.status == "READY"
    assert obj.interpreter == "LLM"
    assert obj.spec is not None
    assert obj.spec.definition_code == "top_productos"


def test_fixture_interpret_aclaracion():
    data = _cargar_fixture("interpret_aclaracion.json")
    obj = InterpretResult.model_validate(data)
    assert obj.status == "NEEDS_CLARIFICATION"
    assert len(obj.questions) > 0


def test_fixture_interpret_no_soportado():
    data = _cargar_fixture("interpret_no_soportado.json")
    obj = InterpretResult.model_validate(data)
    assert obj.status == "UNSUPPORTED"
    assert len(obj.suggestions) > 0


def test_fixture_run_peticion_examen():
    data = _cargar_fixture("run_peticion_examen.json")
    obj = RunIn.model_validate(data)
    assert obj.spec.definition_code == "top_productos"


def test_fixture_run_top_por_sucursal():
    data = _cargar_fixture("run_top_por_sucursal.json")
    obj = ReportResponse.model_validate(data)
    assert obj.definition_code == "top_productos"
    assert obj.groups is not None
    assert len(obj.groups) == 2
    assert obj.groups[0].subtotal["units"] == 23


def test_fixture_run_vacio():
    data = _cargar_fixture("run_vacio.json")
    obj = ReportResponse.model_validate(data)
    assert obj.definition_code == "top_productos"
    assert obj.rows == []
    assert obj.groups == []


def test_fixture_conflictos_lista():
    data = _cargar_fixture("conflictos_lista.json")
    assert "items" in data
    items = [ConflictOut.model_validate(it) for it in data["items"]]
    assert len(items) == 1
    assert items[0].competing_operation is not None
    assert items[0].competing_operation.server_number == "FS-A8F3D1"
    assert items[0].lines[0].competing_operation is not None


def test_fixture_resolver_reintentar_peticion():
    data = _cargar_fixture("resolver_reintentar_peticion.json")
    obj = ConflictResolveIn.model_validate(data)
    assert obj.action == "RETRY"


def test_fixture_resolver_reintentar_ok():
    data = _cargar_fixture("resolver_reintentar_ok.json")
    obj = ConflictOut.model_validate(data)
    assert obj.status == "RESOLVED"
    assert obj.resolution == "RETRY"
