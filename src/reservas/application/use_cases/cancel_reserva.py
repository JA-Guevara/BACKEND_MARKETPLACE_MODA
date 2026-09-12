from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.reservas.application.use_cases.confirm_reserva import ActualizarEstadoReserva
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel


class CancelarReserva:
    def __init__(self, db: Session) -> None:
        self.db = db

    def execute(self, reserva: ReservationModel, actor: UserModel) -> ReservationModel:
        return ActualizarEstadoReserva(self.db).execute(reserva, "cancelled", actor, "Reserva cancelada por el cliente.")
