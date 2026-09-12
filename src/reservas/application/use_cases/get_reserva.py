import uuid

from sqlalchemy.orm import Session

from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.reservas.infrastructure.persistence.repositories.reserva_repository import ReservaRepository
from src.shared.exceptions.domain_exception import NotFoundError


class ObtenerReserva:
    def __init__(self, db: Session) -> None:
        self.repository = ReservaRepository(db)

    def execute(self, reserva_id: uuid.UUID, user_id: uuid.UUID | None = None) -> ReservationModel:
        reserva = self.repository.get(reserva_id, user_id=user_id)
        if not reserva:
            raise NotFoundError("Reserva no encontrada.")
        return reserva
