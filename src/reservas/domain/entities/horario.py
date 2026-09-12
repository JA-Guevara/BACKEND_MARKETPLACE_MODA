from datetime import datetime, timezone

from src.reservas.domain.exceptions import HorarioInvalidoError


def validar_horario(scheduled_at: datetime) -> None:
    """El horario aproximado de la visita (CU12) debe ser una fecha futura."""
    now = datetime.now(timezone.utc)
    reference = scheduled_at if scheduled_at.tzinfo else scheduled_at.replace(tzinfo=timezone.utc)
    if reference <= now:
        raise HorarioInvalidoError("El horario de la visita debe ser posterior al momento actual.")
