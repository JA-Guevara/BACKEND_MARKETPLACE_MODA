"""Los fixtures del kit son contratos, no respuestas simuladas de producción."""
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict
import pytest

from src.auth.infrastructure.http.schemas import LoginRequest
from src.plataforma_saas.web.routers import ops_router
from src.plataforma_saas.web.routers.ops_router import BackupOut, BackupReportIn
from src.plataforma_saas.web.schemas.ops_status import OpsStatusOut
from src.shared.responses.api_response import ApiResponse


FIXTURES = Path(__file__).resolve().parents[4] / "docs/PS-correcciones-liberacion/contrato/fixtures"
pytestmark = pytest.mark.skipif(not FIXTURES.is_dir(), reason="Fixtures del kit no incluidos en esta copia")


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class ErrorBody(BaseModel):
    code: str
    message: str
    details: object | None = None


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    success: Literal[False]
    error: ErrorBody


class ReadyOut(BaseModel):
    status: Literal["ready"]
    revision: str
    version: str


def test_estado_valida_los_dos_contratos_y_error_de_permiso():
    for name in ("ops_status_ok", "ops_status_con_avisos"):
        response = ApiResponse[OpsStatusOut].model_validate(fixture(name))
        assert response.success is True
        assert response.data.config_checks
    response = ErrorEnvelope.model_validate(fixture("ops_status_sin_permiso"))
    assert response.error.code == "permission_denied"


def test_reportes_de_copia_validan_contra_esquemas_reales(monkeypatch):
    class FixtureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)

    # Las fechas de ejemplo pertenecen al 07/11. Cambiar solo el reloj de la
    # prueba evita desactivar la validación temporal del reporte de producción.
    monkeypatch.setattr(ops_router, "datetime", FixtureClock)
    request = BackupReportIn.model_validate(fixture("reporte_diario_revision_previa"))
    response = ApiResponse[BackupOut].model_validate(fixture("reporte_aceptado"))
    assert request.verify_status == response.data.verify_status == "ok"
    assert request.sha256 == response.data.sha256


def test_salud_y_login_tienen_la_forma_del_contrato():
    assert ReadyOut.model_validate(fixture("health_ready")).revision
    assert ErrorEnvelope.model_validate(fixture("health_not_ready")).error.code == "not_ready"
    assert ErrorEnvelope.model_validate(fixture("login_429")).error.code == "rate_limited"
    assert LoginRequest.model_validate(fixture("login_humo")).password
