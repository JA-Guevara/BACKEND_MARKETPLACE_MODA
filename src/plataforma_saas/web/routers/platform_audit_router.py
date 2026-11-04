from datetime import date
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.infrastructure.http.schemas import AuditEventResponse
from src.bitacora.infrastructure.persistence.repositories.bitacora_repository import AuditRepository
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_platform_permissions
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page

router = APIRouter(prefix="/platform", tags=["PAQ-06 · Consola SaaS"])
Reader = Annotated[UserModel, Depends(require_platform_permissions("platform_audit.read"))]


@router.get("/audit", response_model=ApiResponse[Page[AuditEventResponse]])
def get_platform_audit(
    actor: Reader,
    db: Session = Depends(get_db),
    tenant_id: UUID | None = None,
    actor_id: UUID | None = None,
    action: str | None = None,
    support_only: bool = False,
    platform_only: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    repo = AuditRepository(db)
    result_page = repo.page(
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        support_only=support_only,
        platform_only=platform_only,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    items = [AuditEventResponse.model_validate(it) for it in result_page.items]
    data = Page[AuditEventResponse](
        items=items,
        total=result_page.total,
        page=result_page.page,
        page_size=result_page.page_size,
        pages=result_page.pages,
    )
    return ApiResponse(
        message="Operación completada.",
        data=data,
    )
