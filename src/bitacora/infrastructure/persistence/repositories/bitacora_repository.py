import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel


class AuditRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(self, event: AuditEventModel) -> AuditEventModel:
        self.db.add(event)
        self.db.flush()
        return event

    def get(self, event_id: uuid.UUID) -> AuditEventModel | None:
        return self.db.get(AuditEventModel, event_id)

    def list(
        self,
        *,
        page: int,
        page_size: int,
        actor_user_id: uuid.UUID | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[AuditEventModel], int]:
        conditions = []
        if actor_user_id:
            conditions.append(AuditEventModel.actor_user_id == actor_user_id)
        if action:
            conditions.append(AuditEventModel.action == action)
        if entity_type:
            conditions.append(AuditEventModel.entity_type == entity_type)
        if date_from:
            conditions.append(AuditEventModel.created_at >= date_from)
        if date_to:
            conditions.append(AuditEventModel.created_at <= date_to)
        stmt = select(AuditEventModel).where(*conditions)
        count_stmt = select(func.count(AuditEventModel.id)).where(*conditions)
        total = self.db.scalar(count_stmt) or 0
        items = list(
            self.db.scalars(
                stmt.order_by(AuditEventModel.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total


BitacoraRepository = AuditRepository
