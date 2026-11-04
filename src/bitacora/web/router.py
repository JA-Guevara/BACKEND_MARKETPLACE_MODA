import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.infrastructure.http.schemas import AuditEventResponse
from src.bitacora.infrastructure.persistence.repositories.bitacora_repository import BitacoraRepository
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.infrastructure.security.tenancy import TenantScope
from src.shared.exceptions.domain_exception import NotFoundError
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page


router = APIRouter(prefix="/audit-log", tags=["audit log"])
AuditReader = Annotated[UserModel, Depends(require_permissions("audit.read"))]


@router.get("", response_model=ApiResponse[Page[AuditEventResponse]])
def list_events(
    ctx: TenantScope,
    actor: AuditReader,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor_user_id: uuid.UUID | None = None,
    action: str | None = None,
    support_only: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
):
    result = BitacoraRepository(db).page(
        tenant_id=ctx.tenant_id,
        actor_id=actor_user_id,
        action=action,
        support_only=support_only,
        platform_only=False,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(message="Eventos obtenidos.", data=result)


@router.get("/{event_id}", response_model=ApiResponse[AuditEventResponse])
def get_event(
    event_id: uuid.UUID,
    ctx: TenantScope,
    actor: AuditReader,
    db: Session = Depends(get_db),
):
    event = BitacoraRepository(db).get(event_id)
    if not event:
        raise NotFoundError("Evento de bitacora no encontrado.")
    if ctx.tenant_id is not None and event.tenant_id != ctx.tenant_id:
        raise NotFoundError("Evento de bitacora no encontrado.")
    return ApiResponse(message="Evento obtenido.", data=event)
