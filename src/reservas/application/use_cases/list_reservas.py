import uuid

from sqlalchemy.orm import Session

from src.reservas.infrastructure.persistence.repositories.reserva_repository import ReservaRepository


class ListarReservas:
    def __init__(self, db: Session) -> None:
        self.repository = ReservaRepository(db)

    def execute(
        self,
        *,
        page: int,
        page_size: int,
        user_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
        status: str | None = None,
        q: str | None = None,
        date_from=None,
        date_to=None,
        order: str = "scheduled_at",
        direction: str = "desc",
    ):
        return self.repository.list(
            page=page,
            page_size=page_size,
            user_id=user_id,
            branch_id=branch_id,
            status=status,
            q=q,
            date_from=date_from,
            date_to=date_to,
            order=order,
            direction=direction,
        )
