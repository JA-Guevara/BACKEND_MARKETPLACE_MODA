"""Contrato público de observabilidad; nunca incluye valores de configuración."""
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ConfigCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal[
        "app_env_not_production", "backup_report_token_missing", "forwarded_ips_untrusted",
        "migration_exception_active", "workers_multiple", "backup_stale", "sentry_missing",
    ]
    level: Literal["error", "warning", "info"]
    message: str


class LastVerifiedBackup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    finished_at: AwareDatetime
    age_hours: float = Field(ge=0, allow_inf_nan=False)
    alembic_revision: str | None


class MFAAdoption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    habilitadas: int | None = Field(default=None, ge=0)


class OpsCounters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate_limited: int | None = Field(default=None, ge=0)
    errors_5xx: int = Field(default=0, ge=0)
    rate_limited_by_policy: dict[str, int] = Field(default_factory=dict)
    sync_rechazadas_24h: int = Field(ge=0)
    cuentas_bloqueadas: int = Field(ge=0)
    mfa_adopcion: MFAAdoption


class OpsStatusOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    git_sha: str | None
    app_env: Literal["local", "test", "staging", "production"]
    revision_bd: str | None
    cabeza_codigo: str | None
    migraciones_pendientes: bool
    ultimo_respaldo: LastVerifiedBackup | None
    mantenimiento: bool
    contadores: OpsCounters
    config_checks: list[ConfigCheck] = Field(default_factory=list)
