"""Consulta del estado de un trabajo.

Consumir el estado dispara el trabajo pendiente (procesamiento lazy) y hace
cumplir la política de privacidad: si el plazo venció, se borran la foto de la
persona y el resultado; el trabajo queda `expired` y la URL no responde más.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.shared.exceptions.domain_exception import NotFoundError
from src.tryon_ai_jobs.application.procesar_trabajo import procesar_trabajo
from src.tryon_ai_jobs.domain import ACTIVOS, ESTADO_EXPIRADO
from src.tryon_ai_jobs.infrastructure.persistence.models.tryon_job import TryOnJobModel
from src.tryon_ai_jobs.infrastructure.services import archivos


class ConsultarTrabajo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def execute(self, user, trabajo_id: uuid.UUID) -> TryOnJobModel:
        trabajo = self._de_este_usuario(user.id, trabajo_id)
        if self._vencio(trabajo) and trabajo.status != ESTADO_EXPIRADO:
            self._expirar(trabajo)
        elif trabajo.status in ACTIVOS:
            procesar_trabajo(self.db, trabajo)
        return trabajo

    def _de_este_usuario(self, user_id: uuid.UUID, trabajo_id: uuid.UUID) -> TryOnJobModel:
        trabajo = self.db.get(TryOnJobModel, trabajo_id)
        if not trabajo or trabajo.user_id != user_id:
            raise NotFoundError("Trabajo no encontrado.")
        return trabajo

    @staticmethod
    def _vencio(trabajo: TryOnJobModel) -> bool:
        if not trabajo.expires_at:
            return False
        referencia = trabajo.expires_at
        if referencia.tzinfo is None:
            referencia = referencia.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > referencia

    def _expirar(self, trabajo: TryOnJobModel) -> None:
        # Borrado real de la foto de la persona y del resultado anterior.
        archivos.borrar_archivo(trabajo.person_photo_url)
        archivos.borrar_archivo(trabajo.result_url)
        trabajo.status = ESTADO_EXPIRADO
        trabajo.error = "La foto IA expiró y se eliminó por privacidad."
        RecordAuditEvent(self.db).execute(
            action="tryon_ai.job_expired",
            entity_type="tryon_ai_job",
            entity_id=str(trabajo.id),
            description="El trabajo de foto IA expiró y sus imágenes se eliminaron.",
            actor_user_id=trabajo.user_id,
        )
        self.db.commit()
        self.db.refresh(trabajo)