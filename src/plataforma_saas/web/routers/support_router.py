import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.access_context import AccessContext, get_access_context
from src.infrastructure.security.authorization import require_platform_permissions
from src.plataforma_saas.application.support_service import SupportService
from src.plataforma_saas.web.schemas.support import (
    SupportSessionCreate,
    SupportSessionExtend,
    SupportSessionResponse,
    SupportSessionStart,
)
from src.shared.exceptions.domain_exception import AuthorizationError
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page


router = APIRouter(tags=["PAQ-06 · Plataforma SaaS"])
SupportAccessUser = Annotated[UserModel, Depends(require_platform_permissions("support.access"))]
PlatformAuditUser = Annotated[UserModel, Depends(require_platform_permissions("platform_audit.read"))]


def _request_client_info(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ip, ua


@router.post(
    "/platform/tenants/{tenant_id}/support-sessions",
    response_model=ApiResponse[SupportSessionStart],
    status_code=status.HTTP_201_CREATED,
)
def start_support_session(
    tenant_id: uuid.UUID,
    data: SupportSessionCreate,
    actor: SupportAccessUser,
    request: Request,
    db: Session = Depends(get_db),
):
    ip, ua = _request_client_info(request)
    result = SupportService(db, actor).iniciar(
        tenant_id=tenant_id,
        reason=data.reason,
        duration_minutes=data.duration_minutes,
        ip=ip,
        ua=ua,
    )
    return ApiResponse(message="Sesión de soporte iniciada.", data=result)


@router.post(
    "/platform/support-sessions/{session_id}/extend",
    response_model=ApiResponse[SupportSessionStart],
)
def extend_support_session(
    session_id: uuid.UUID,
    data: SupportSessionExtend = SupportSessionExtend(),
    ctx: AccessContext = Depends(get_access_context),
    db: Session = Depends(get_db),
):
    if ctx.user.tenant_id is not None:
        raise AuthorizationError("Esta operación requiere un usuario de plataforma.")
    has_perm = any(
        p.code == "support.access" and getattr(p, "is_active", True)
        for r in ctx.user.roles
        if getattr(r, "is_active", True)
        for p in r.permissions
    )
    if not has_perm:
        raise AuthorizationError("No tiene permisos para extender la sesión de soporte.")

    result = SupportService(db, ctx.user).extender(session_id, data.minutes)
    return ApiResponse(message="Sesión de soporte extendida.", data=result)


@router.post(
    "/platform/support-sessions/{session_id}/end",
    response_model=ApiResponse[SupportSessionResponse],
)
def end_support_session(
    session_id: uuid.UUID,
    ctx: AccessContext = Depends(get_access_context),
    db: Session = Depends(get_db),
):
    if ctx.user.tenant_id is not None:
        raise AuthorizationError("Esta operación requiere un usuario de plataforma.")

    result = SupportService(db, ctx.user).terminar(session_id, reason="manual")
    return ApiResponse(message="Sesión de soporte finalizada.", data=result)


@router.get(
    "/platform/support-sessions",
    response_model=ApiResponse[Page[SupportSessionResponse]],
)
def list_support_sessions(
    actor: PlatformAuditUser,
    tenant_id: uuid.UUID | None = None,
    platform_user_id: uuid.UUID | None = None,
    active: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = SupportService(db, actor).listar(
        tenant_id=tenant_id,
        platform_user_id=platform_user_id,
        active=active,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(message="Sesiones de soporte obtenidas.", data=result)
