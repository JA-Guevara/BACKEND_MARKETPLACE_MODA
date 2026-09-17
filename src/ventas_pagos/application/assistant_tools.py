"""Ejecucion de herramientas tipadas del asistente de reportes.

El asistente puede ejecutar SOLO las herramientas registradas en este archivo
(allowlist). Cada ejecucion valida los parametros con el mismo motor de la capa
web, genera el archivo con ``MultiExportService`` y deja bitacora con el correo
del actor. Una misma ``request_id`` (generada en el navegador de la sesion) se
se audita una sola vez: si se repite dentro de la ventana TTL, se regenera
el archivo con datos actuales sin duplicar la auditoria, y se avisa con el encabezado
``X-Idempotent-Replay`` (politica best-effort en memoria).
"""
from dataclasses import dataclass
from hashlib import sha256
from threading import Lock
from time import monotonic
from typing import Literal

from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.ventas_pagos.application.multi_export_service import MultiExportService
from src.ventas_pagos.web.schemas import ExportReportToolParams, ReportFilters

ALLOWED_TOOLS: set[str] = {"export_report"}
ToolName = Literal["export_report"]

IDEMPOTENCY_TTL_SECONDS = 60.0


class UnknownToolError(Exception):
    """La herramienta pedida no existe en el registro autorizado."""


@dataclass
class AssistantToolResult:
    payload: object
    media_type: str
    filename: str
    reports: list[str]
    truncated: bool
    audited: bool
    replay: bool


class _IdempotencyStore:
    """Cache de request_ids ya procesados por usuario (best-effort, en memoria)."""

    def __init__(self, ttl_seconds: float = IDEMPOTENCY_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._seen: dict[str, float] = {}
        self._lock = Lock()

    def _key(self, actor_id, request_id) -> str:
        return f"{actor_id}:{request_id}"

    def claim(self, actor_id, request_id) -> bool:
        """Devuelve True si la operacion se ve por primera vez (la clama);
        False si ya se vio dentro de la ventana TTL (replay a ignorar)."""
        key = self._key(actor_id, request_id)
        now = monotonic()
        with self._lock:
            self._seen = {k: t for k, t in self._seen.items() if now - t < self.ttl_seconds}
            if key in self._seen:
                return False
            self._seen[key] = now
            return True


_store = _IdempotencyStore()


class AssistantTools:
    """Caso de uso del asistente: valida la herramienta, la ejecuta con datos
    reales autorizados y registra la accion en bitacora."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.service = MultiExportService(db)

    def execute(
        self,
        tool: ToolName,
        params: ExportReportToolParams | None,
        actor: UserModel,
        request_id: str | None,
    ) -> AssistantToolResult:
        if tool not in ALLOWED_TOOLS:
            raise UnknownToolError(f'Herramienta no autorizada: "{tool}".')
        if tool == "export_report":
            return self._export_report(params, actor, request_id)
        raise UnknownToolError(f'Herramienta no autorizada: "{tool}".')

    def _export_report(
        self,
        params: ExportReportToolParams | None,
        actor: UserModel,
        request_id: str | None,
    ) -> AssistantToolResult:
        if params is None:
            raise ValueError("La herramienta export_report requiere parametros.")
        filters = params.filters or ReportFilters()
        payload, media_type, filename, summary = self.service.export(
            params.reports, params.format, filters
        )
        # An export that failed must not suppress the audit of its successful
        # retry. Different parameters are distinct operations even if a client
        # mistakenly reuses the same request identifier.
        fingerprint = sha256(params.model_dump_json().encode()).hexdigest()
        replay = bool(request_id) and not _store.claim(actor.id, f'{request_id}:{fingerprint}')
        if not replay:
            RecordAuditEvent(self.db).execute(
                action="analytics.tool_export_report",
                entity_type="report",
                entity_id="+".join(params.reports),
                description="El asistente ejecuto la herramienta export_report con los filtros visibles.",
                actor_user_id=actor.id,
                metadata={
                    "tool": "export_report",
                    "actor_email": actor.email,
                    "request_id": request_id,
                    "reports": params.reports,
                    "format": params.format,
                    "filtros": summary["filtros"],
                    "periodo": summary["periodo"],
                    "truncated": summary["truncated"],
                },
            )
            self.db.commit()
        return AssistantToolResult(
            payload=payload,
            media_type=media_type,
            filename=filename,
            reports=summary["reports"],
            truncated=summary["truncated"],
            audited=not replay,
            replay=replay,
        )
