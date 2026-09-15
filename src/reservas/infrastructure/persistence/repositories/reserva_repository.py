import uuid

from sqlalchemy import func, or_, select, String
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
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

    def get_by_client_key(self, user_id: uuid.UUID, client_key: str) -> ReservationModel | None:
        return self.db.scalar(
            select(ReservationModel).where(
                ReservationModel.user_id == user_id,
                ReservationModel.client_key == client_key,
            )
        )

    def list(
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
    ) -> tuple[list[ReservationModel], int]:
        conditions = []
        if user_id is not None:
            conditions.append(ReservationModel.user_id == user_id)
        if branch_id is not None:
            conditions.append(ReservationModel.branch_id == branch_id)
        if status:
            conditions.append(ReservationModel.status == status)
        if q:
            like = f"%{q.strip()}%"
            conditions.append(
                or_(
                    UserModel.email.ilike(like),
                    UserModel.first_name.ilike(like),
                    UserModel.last_name.ilike(like),
                    func.cast(ReservationModel.id, String).ilike(like),
                )
            )
        if date_from is not None:
            conditions.append(ReservationModel.scheduled_at >= date_from)
        if date_to is not None:
            conditions.append(ReservationModel.scheduled_at <= date_to)

        stmt = select(ReservationModel)
        count_stmt = select(func.count(ReservationModel.id))
        if q:
            stmt = stmt.join(UserModel, UserModel.id == ReservationModel.user_id)
            count_stmt = count_stmt.join(UserModel, UserModel.id == ReservationModel.user_id)
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

        total = self.db.scalar(count_stmt) or 0
        column = getattr(ReservationModel, order, ReservationModel.scheduled_at)
        ordered = column.asc() if direction == "asc" else column.desc()
        items = list(
            self.db.scalars(
                stmt.order_by(ordered)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total
