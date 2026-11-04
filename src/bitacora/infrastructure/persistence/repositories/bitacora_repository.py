from datetime import date, datetime, time, timezone
from math import ceil
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.shared.responses.pagination import Page


class AuditRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(self, event: AuditEventModel) -> AuditEventModel:
        self.db.add(event)
        self.db.flush()
        return event

    def get(self, event_id: uuid.UUID) -> AuditEventModel | None:
        return self.db.get(AuditEventModel, event_id)

    def page(
        self,
        *,
        tenant_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        action: str | None = None,
        support_only: bool = False,
        platform_only: bool = False,
        date_from: date | None = None,
        date_to: date | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Page:
        conditions = []
        if tenant_id is not None:
            conditions.append(AuditEventModel.tenant_id == tenant_id)
        if actor_id:
            conditions.append(AuditEventModel.actor_user_id == actor_id)
        if action:
            conditions.append(AuditEventModel.action == action)
        if support_only:
            conditions.append(AuditEventModel.support_session_id.is_not(None))
        if platform_only:
            conditions.append(AuditEventModel.tenant_id.is_(None))
        if date_from:
            dt_from = datetime.combine(date_from, time.min).replace(tzinfo=timezone.utc)
            conditions.append(AuditEventModel.created_at >= dt_from)
        if date_to:
            dt_to = datetime.combine(date_to, time.max).replace(tzinfo=timezone.utc)
            conditions.append(AuditEventModel.created_at <= dt_to)

        count_stmt = select(func.count(AuditEventModel.id)).where(*conditions)
        total = self.db.scalar(count_stmt) or 0
        pages = ceil(total / page_size) if total else 0

        stmt = (
            select(AuditEventModel)
            .where(*conditions)
            .order_by(AuditEventModel.created_at.desc(), AuditEventModel.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(self.db.scalars(stmt).all())
        return Page(items=items, total=total, page=page, page_size=page_size, pages=pages)

    def list(
        self,
        *,
        page: int,
        page_size: int,
        actor_user_id: uuid.UUID | None = None,
        actor_query: str | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[AuditEventModel], int]:
        conditions = []
        if actor_user_id:
            conditions.append(AuditEventModel.actor_user_id == actor_user_id)
        if actor_query and actor_query.strip():
            term = actor_query.strip().lower()
            conditions.append(AuditEventModel.actor.has(or_(
                func.lower(UserModel.email).contains(term, autoescape=True),
                func.lower(UserModel.first_name + " " + UserModel.last_name).contains(term, autoescape=True),
            )))
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
                stmt.order_by(AuditEventModel.created_at.desc(), AuditEventModel.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total


BitacoraRepository = AuditRepository
