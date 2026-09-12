import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.reservas.infrastructure.persistence.models.reserva import ReservationModel


class ReservaRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, reserva: ReservationModel) -> ReservationModel:
        self.db.add(reserva)
        self.db.flush()
        return reserva

    def get(self, reserva_id: uuid.UUID, user_id: uuid.UUID | None = None) -> ReservationModel | None:
        query = select(ReservationModel).where(ReservationModel.id == reserva_id)
        if user_id is not None:
            query = query.where(ReservationModel.user_id == user_id)
        return self.db.scalar(query.with_for_update())

    def list(
        self,
        *,
        page: int,
        page_size: int,
        user_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> tuple[list[ReservationModel], int]:
        conditions = []
        if user_id is not None:
            conditions.append(ReservationModel.user_id == user_id)
        if branch_id is not None:
            conditions.append(ReservationModel.branch_id == branch_id)
        if status:
            conditions.append(ReservationModel.status == status)
        stmt = select(ReservationModel).where(*conditions)
        count_stmt = select(func.count(ReservationModel.id)).where(*conditions)
        total = self.db.scalar(count_stmt) or 0
        items = list(
            self.db.scalars(
                stmt.order_by(ReservationModel.scheduled_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total
