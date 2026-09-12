from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.reservas.domain.entities.reserva import TRANSITIONS
from src.reservas.domain.exceptions import TransicionInvalidaError
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel

STATUS_NOTES = {
    "confirmed": "Sucursal confirmo la reserva y prepara las prendas.",
    "ready": "Prendas preparadas; a la espera del cliente.",
    "attended": "Cliente atendido en sucursal.",
    "cancelled": "Reserva cancelada.",
}


class ActualizarEstadoReserva:
    """Cubre CU14 (atender reserva: confirmar, preparar, confirmar recepcion) y
    la cancelacion (CU13), que es la misma maquina de estados con distinto destino."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def execute(self, reserva: ReservationModel, nuevo_estado: str, actor: UserModel, note: str = "") -> ReservationModel:
        allowed = TRANSITIONS.get(reserva.status, set())
        if nuevo_estado not in allowed:
            raise TransicionInvalidaError(f"No se puede pasar de '{reserva.status}' a '{nuevo_estado}'.")
        reserva.status = nuevo_estado
        reserva.tracking = [
            *reserva.tracking,
            {"status": nuevo_estado, "note": note or STATUS_NOTES.get(nuevo_estado, "Estado actualizado."), "date": datetime.now(timezone.utc).isoformat()},
        ]
        RecordAuditEvent(self.db).execute(
            action="reservas.status_changed" if nuevo_estado != "cancelled" else "reservas.cancelled",
            entity_type="reservation",
            entity_id=str(reserva.id),
            description=STATUS_NOTES.get(nuevo_estado, "Estado de la reserva actualizado."),
            actor_user_id=actor.id,
            metadata={"status": nuevo_estado},
        )
        self.db.commit()
        self.db.refresh(reserva)
        return reserva
