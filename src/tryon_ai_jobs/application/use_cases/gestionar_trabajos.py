"""Listado, cancelación y eliminación de trabajos de foto IA.

Nada de esto es cosmético: cancelar o eliminar borra la foto de la persona del
disco. Quien pidió el trabajo es el único que puede tocarlo.
"""
import uuid

from sqlalchemy.orm import Session

from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError
from src.tryon_ai_jobs.domain import ACTIVOS, ESTADO_CANCELADO
from src.tryon_ai_jobs.infrastructure.persistence.models.tryon_job import TryOnJobModel
from src.tryon_ai_jobs.infrastructure.services import archivos


class ListarTrabajos:
    def __init__(self, db: Session) -> None:
        self.db = db

    def execute(self, user) -> list[TryOnJobModel]:
        trabajos = (
            self.db.query(TryOnJobModel)
            .filter(TryOnJobModel.user_id == user.id)
            .order_by(TryOnJobModel.created_at.desc())
            .all()
        )
        return list(trabajos)


class CancelarTrabajo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def execute(self, user, trabajo_id: uuid.UUID) -> TryOnJobModel:
        trabajo = self._de_este_usuario(self.db, user.id, trabajo_id)
        if trabajo.status not in ACTIVOS:
            raise ValidationError("Este trabajo ya terminó; no se puede cancelar.")
        archivos.borrar_archivo(trabajo.person_photo_url)
        archivos.borrar_archivo(trabajo.result_url)
        trabajo.status = ESTADO_CANCELADO
        trabajo.error = "Cancelado por el usuario; la foto se eliminó."
        RecordAuditEvent(self.db).execute(
            action="tryon_ai.job_cancelled",
            entity_type="tryon_ai_job",
            entity_id=str(trabajo.id),
            description="El usuario canceló la foto IA y se eliminó la imagen.",
            actor_user_id=user.id,
        )
        self.db.commit()
        self.db.refresh(trabajo)
        return trabajo

    @staticmethod
    def _de_este_usuario(
        db: Session, user_id: uuid.UUID, trabajo_id: uuid.UUID
    ) -> TryOnJobModel:
        trabajo = (
            db.query(TryOnJobModel)
            .filter(TryOnJobModel.id == trabajo_id, TryOnJobModel.user_id == user_id)
            .first()
        )
        if not trabajo:
            raise NotFoundError("Trabajo no encontrado.")
        return trabajo


class EliminarTrabajo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def execute(self, user, trabajo_id: uuid.UUID) -> None:
        db = self.db
        trabajo = (
            db.query(TryOnJobModel)
            .filter(TryOnJobModel.id == trabajo_id, TryOnJobModel.user_id == user.id)
            .first()
        )
        if not trabajo:
            raise NotFoundError("Trabajo no encontrado.")
        archivos.borrar_archivo(trabajo.person_photo_url)
        archivos.borrar_archivo(trabajo.result_url)
        RecordAuditEvent(db).execute(
            action="tryon_ai.job_deleted",
            entity_type="tryon_ai_job",
            entity_id=str(trabajo.id),
            description="El trabajo de foto IA y sus imágenes se eliminaron.",
            actor_user_id=user.id,
        )
        db.delete(trabajo)
        db.commit()