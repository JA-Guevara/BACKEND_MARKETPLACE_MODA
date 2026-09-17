import uuid

from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.probador_virtual.domain.entities.experiencia_virtual import ExperienciaVirtual
from src.probador_virtual.infrastructure.services.virtual_fitting_service import VirtualFittingService


class IniciarExperiencia:
    """CU16 Utilizar vestidor virtual: valida el recurso AR del producto y
    deja registro en bitacora de que el cliente abrio la experiencia."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.service = VirtualFittingService(db)

    def execute(
        self, product_id: uuid.UUID, user: UserModel, color_id: uuid.UUID | None = None
    ) -> ExperienciaVirtual:
        experiencia = self.service.resolve_asset(product_id, color_id)
        RecordAuditEvent(self.db).execute(
            action="probador_virtual.session_started",
            entity_type="product",
            entity_id=str(product_id),
            description="Cliente abrio el vestidor virtual para una prenda.",
            actor_user_id=user.id,
            metadata={
                "asset_type": experiencia.asset_type,
                "body_region": experiencia.body_region,
                "color_id": str(experiencia.color_id) if experiencia.color_id else None,
            },
        )
        self.db.commit()
        return experiencia
