from datetime import datetime, timezone
import hmac
import os
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.infrastructure.config.settings import settings
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_platform_permissions
from src.plataforma_saas.application.jobs.runner import TareasProgramadas
from src.plataforma_saas.application.ops_service import OpsService
from src.plataforma_saas.web.schemas.ops_status import OpsStatusOut
from src.plataforma_saas.infrastructure.models.ops import JobRunModel
from src.shared.exceptions.domain_exception import AuthenticationError
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page


router = APIRouter(prefix="/platform/ops", tags=["PAQ-06 · Operación de plataforma"])
Reader = Annotated[UserModel, Depends(require_platform_permissions("platform.ops.read"))]
Writer = Annotated[UserModel, Depends(require_platform_permissions("platform.ops.write"))]
_service_bearer = HTTPBearer(auto_error=False, scheme_name="BackupReportToken")

Revision = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")]
RunURL = Annotated[str, Field(
    max_length=300,
    pattern=r"^https://github\.com/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+/actions/runs/[0-9]+(?:/attempts/[0-9]+)?$",
)]
RequiredChecks = {"revision", "tablas_clave", "permisos", "esquema"}


class BackupCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    ok: bool
    details: dict = Field(default_factory=dict, max_length=20)

    @field_validator("details")
    @classmethod
    def validar_detalles(cls, details: dict) -> dict:
        numeric = {"tenants", "users", "products", "permissions", "expected", "actual", "count", "missing", "extra", "wrong_id"}
        revisions = {"expected", "actual", "revision"}
        for key, value in details.items():
            if key in numeric and type(value) is int and value >= 0:
                continue
            if key in revisions and (value is None or isinstance(value, str) and _revision_conocida(value)):
                continue
            if key == "code" and value in ("restauracion_fallida", "verificacion_fallida", "backup_failed"):
                continue
            raise ValueError("El detalle de comprobación debe contener solo metadatos de restauración.")
        return details


def _revision_conocida(value: str) -> bool:
    # Los valores que salen de Alembic son identificadores cortos, nunca una cadena de conexión.
    return 1 <= len(value) <= 40 and value.isascii() and value.replace("_", "").replace("-", "").isalnum()


class VerificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)
    alembic_revision: Revision | None = None
    checks: list[BackupCheck] = Field(max_length=20)


class BackupReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["daily", "weekly", "pre_migration", "manual"]
    started_at: AwareDatetime
    finished_at: AwareDatetime
    size_bytes: int = Field(ge=0, le=2**63 - 1)
    sha256: str | None = Field(None, pattern=r"^[a-fA-F0-9]{64}$")
    storage_ref: str | None = Field(None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
    alembic_revision: Revision | None = None
    pg_server_version: int | None = Field(None, gt=0, le=2**31 - 1)
    verify_status: Literal["ok", "failed", "pending"]
    verify_report: VerificationReport | None = None
    workflow_run_url: RunURL | None = None

    @model_validator(mode="after")
    def validar_copia(self):
        if self.started_at > self.finished_at or self.finished_at > datetime.now(timezone.utc):
            raise ValueError("La fecha de la copia debe corresponder a un intervalo ya transcurrido.")
        self.started_at = self.started_at.astimezone(timezone.utc)
        self.finished_at = self.finished_at.astimezone(timezone.utc)

        artifact_data = (self.storage_ref, self.alembic_revision, self.pg_server_version)
        if self.sha256 is None:
            if self.verify_status != "failed" or self.size_bytes != 0 or any(artifact_data) or not self.workflow_run_url:
                raise ValueError("Un reporte sin copia debe identificar un intento fallido de GitHub.")
        elif self.size_bytes == 0 or not all(artifact_data):
            raise ValueError("La copia requiere tamaño, ubicación, revisión y versión del servidor.")
        else:
            self.sha256 = self.sha256.lower()

        if self.verify_status == "ok":
            report = self.verify_report
            if not report or not report.ok or report.alembic_revision != self.alembic_revision:
                raise ValueError("La verificación debe corresponder a la revisión de la copia.")
            if not RequiredChecks.issubset({check.name for check in report.checks}) or any(not check.ok for check in report.checks):
                raise ValueError("La copia requiere restauración y todas las comprobaciones aprobadas.")
        elif self.verify_report and self.verify_report.ok:
            raise ValueError("El estado del respaldo no coincide con el resultado de verificación.")
        return self


class BackupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    started_at: datetime
    finished_at: datetime
    size_bytes: int
    sha256: str | None
    storage_ref: str | None
    alembic_revision: str | None
    pg_server_version: int | None
    verify_status: str
    verify_report: dict | None
    workflow_run_url: str | None
    created_at: datetime

    @field_validator("started_at", "finished_at", "created_at")
    @classmethod
    def fecha_utc(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class DispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=3, max_length=300)


def _authenticate_report(credentials: HTTPAuthorizationCredentials | None = Depends(_service_bearer)) -> None:
    secret = settings.backup_report_token
    expected = secret.get_secret_value() if secret is not None else ""
    if not expected or credentials is None or not hmac.compare_digest(credentials.credentials.encode(), expected.encode()):
        raise AuthenticationError("El token de servicio del respaldo no es válido.")


@router.post("/backups", response_model=ApiResponse[BackupOut], dependencies=[Depends(_authenticate_report)])
def report_backup(body: BackupReportIn, db: Session = Depends(get_db)):
    result = OpsService(db).registrar_respaldo(body.model_dump())
    return ApiResponse(data=BackupOut.model_validate(result))


@router.get("/backups", response_model=ApiResponse[Page[BackupOut]])
def list_backups(
    actor: Reader, db: Session = Depends(get_db),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
):
    return ApiResponse(data=Page[BackupOut].model_validate(OpsService(db).listar_respaldos(page, page_size)))


@router.get("/status", response_model=ApiResponse[OpsStatusOut])
def operations_status(request: Request, actor: Reader, db: Session = Depends(get_db)):
    result = OpsService(db).estado(
        version=request.app.version,
        rate_limited=getattr(request.app.state, "rate_limited_count", None),
        errors_5xx=getattr(request.app.state, "server_error_count", 0),
        rate_limited_by_policy=getattr(request.app.state, "rate_limited_by_policy", {}),
    )
    return ApiResponse(data=result)


@router.post("/backups/dispatch", response_model=ApiResponse[dict])
def dispatch_backup(body: DispatchRequest, actor: Writer, db: Session = Depends(get_db)):
    return ApiResponse(data=OpsService(db).despachar_respaldo(actor, body.reason))


_jobs_bearer = HTTPBearer(auto_error=False, scheme_name="JobsToken")


def _authenticate_jobs(credentials: HTTPAuthorizationCredentials | None = Depends(_jobs_bearer)) -> None:
    expected = os.environ.get("JOBS_TOKEN")
    if not expected and settings.jobs_token is not None:
        expected = settings.jobs_token.get_secret_value()
    expected = expected or ""
    if not expected or credentials is None or not hmac.compare_digest(credentials.credentials.encode(), expected.encode()):
        raise AuthenticationError("El token de servicio de tareas programadas no es válido.")


class JobRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    changes: dict | None = None
    error: str | None = None

    @field_validator("started_at", "finished_at")
    @classmethod
    def fecha_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@router.post("/jobs/tick", response_model=ApiResponse[list[JobRunOut]], dependencies=[Depends(_authenticate_jobs)])
def trigger_jobs_tick(db: Session = Depends(get_db)):
    runs = TareasProgramadas(db).tick()
    return ApiResponse(data=[JobRunOut.model_validate(r) for r in runs])


@router.get("/jobs", response_model=ApiResponse[list[JobRunOut]])
def list_jobs(actor: Reader, db: Session = Depends(get_db)):
    runs = db.scalars(
        select(JobRunModel).order_by(JobRunModel.started_at.desc()).limit(50)
    ).all()
    return ApiResponse(data=[JobRunOut.model_validate(r) for r in runs])


@router.post("/jobs/run", response_model=ApiResponse[list[JobRunOut]])
def manual_run_jobs(body: DispatchRequest, actor: Writer, db: Session = Depends(get_db)):
    runs = TareasProgramadas(db).tick()
    RecordAuditEvent(db).execute(
        action="platform.ops.jobs_run",
        entity_type="jobs",
        entity_id="tick",
        description=f"Ejecución manual de tareas programadas: {body.reason}",
        actor_user_id=actor.id,
    )
    db.commit()
    return ApiResponse(data=[JobRunOut.model_validate(r) for r in runs])
