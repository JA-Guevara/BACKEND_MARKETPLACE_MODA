from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.reservas.application.dto.reserva_dto import ReservaItemSnapshot
from src.reservas.domain.entities.horario import validar_horario
from src.reservas.infrastructure.http.schemas import CrearReservaRequest
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.reservas.infrastructure.persistence.repositories.reserva_repository import ReservaRepository
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError
from src.usuarios_catalogo.infrastructure.models.catalog import ProductVariantModel


class CrearReserva:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = ReservaRepository(db)

    def _branch(self, branch_id) -> BranchModel:
        branch = self.db.get(BranchModel, branch_id)
        if not branch or not branch.is_active or branch.deleted_at:
            raise ValidationError("Sucursal no disponible.")
        return branch

    def _snapshot(self, variant_id, quantity: int) -> ReservaItemSnapshot:
        variant = self.db.get(ProductVariantModel, variant_id)
        if not variant or not variant.is_active or not variant.product.is_active or variant.product.deleted_at:
            raise NotFoundError("Una de las prendas seleccionadas ya no esta disponible.")
        return ReservaItemSnapshot(
            variant_id=str(variant.id),
            product_id=str(variant.product_id),
            name=variant.product.name,
            sku=variant.sku,
            size=variant.size.name,
            color=variant.color.name,
            image_url=variant.product.images[0].url if variant.product.images else None,
            quantity=quantity,
        )

    def execute(self, user: UserModel, data: CrearReservaRequest) -> ReservationModel:
        self._branch(data.branch_id)
        validar_horario(data.scheduled_at)
        items = [self._snapshot(item.variant_id, item.quantity).as_dict() for item in data.items]
        reserva = ReservationModel(
            user_id=user.id,
            branch_id=data.branch_id,
            status="pending",
            scheduled_at=data.scheduled_at,
            items=items,
            notes=data.notes,
            tracking=[
                {
                    "status": "pending",
                    "note": "Reserva registrada; pendiente de confirmacion de la sucursal.",
                    "date": datetime.now(timezone.utc).isoformat(),
                }
            ],
        )
        self.repository.add(reserva)
        RecordAuditEvent(self.db).execute(
            action="reservas.created",
            entity_type="reservation",
            entity_id=str(reserva.id),
            description="Reserva de prendas registrada para probar en sucursal.",
            actor_user_id=user.id,
            metadata={"branch_id": str(data.branch_id), "items": len(items), "scheduled_at": data.scheduled_at.isoformat()},
        )
        self.db.commit()
        self.db.refresh(reserva)
        return reserva
