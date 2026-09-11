import uuid
from datetime import datetime
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.infrastructure.http.schemas import AuditEventResponse
from src.bitacora.infrastructure.persistence.repositories.bitacora_repository import AuditRepository
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.shared.exceptions.domain_exception import NotFoundError
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page


router = APIRouter(prefix="/audit-log", tags=["audit log"])
AuditReader = Annotated[UserModel, Depends(require_permissions("audit.read"))]


@router.get("", response_model=ApiResponse[Page[AuditEventResponse]])
def list_events(
    actor: AuditReader,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor_user_id: uuid.UUID | None = None,
    actor_query: str | None = Query(None, max_length=320),
    action: str | None = None,
    entity_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    items, total = AuditRepository(db).list(
        page=page,
        page_size=page_size,
        actor_user_id=actor_user_id,
        actor_query=actor_query,
        action=action,
        entity_type=entity_type,
        date_from=date_from,
        date_to=date_to,
    )
    result = Page(items=items, total=total, page=page, page_size=page_size, pages=ceil(total / page_size) if total else 0)
    return ApiResponse(message="Eventos obtenidos.", data=result)


@router.get("/{event_id}", response_model=ApiResponse[AuditEventResponse])
def get_event(event_id: uuid.UUID, actor: AuditReader, db: Session = Depends(get_db)):
    event = AuditRepository(db).get(event_id)
    if not event:
        raise NotFoundError("Evento de bitacora no encontrado.")
    return ApiResponse(message="Evento obtenido.", data=event)
