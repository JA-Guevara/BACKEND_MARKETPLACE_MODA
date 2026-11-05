from datetime import date, datetime, timezone
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.infrastructure.security.tenancy import TenantScope
from src.plataforma_saas.application.support_service import SupportService
from src.plataforma_saas.application.tenant_admin_service import TenantAdminService
from src.plataforma_saas.web.schemas.support import (
    SupportApprovalRequest,
    SupportPolicyUpdate,
    SupportRejectionRequest,
    SupportSessionResponse,
)
from src.plataforma_saas.web.schemas.tenant_admin import (
    TenantDashboard,
    TenantProfile,
    TenantProfileUpdate,
)
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page

router = APIRouter(prefix="/tenant", tags=["PAQ-06 · Plataforma SaaS"])

DashboardReader = Annotated[UserModel, Depends(require_permissions("dashboard.read"))]
SubscriptionReader = Annotated[UserModel, Depends(require_permissions("my_subscription.read"))]
ProfileWriter = Annotated[UserModel, Depends(require_permissions("tenant_profile.write"))]
SupportSessionReader = Annotated[UserModel, Depends(require_permissions("support_sessions.read"))]
SupportApprover = Annotated[UserModel, Depends(require_permissions("support_access.approve"))]


@router.get("/dashboard", response_model=ApiResponse[TenantDashboard])
def get_dashboard(
    ctx: TenantScope,
    actor: DashboardReader,
    branch_id: UUID | None = None,
    today: date | None = None,
    db: Session = Depends(get_db),
):
    current_date = today or datetime.now(timezone.utc).date()
    service = TenantAdminService(db, ctx)
    return ApiResponse(
        message="Operación completada.",
        data=service.panel(branch_id=branch_id, today=current_date),
    )


@router.get("/profile", response_model=ApiResponse[TenantProfile])
def get_profile(
    ctx: TenantScope,
    actor: SubscriptionReader,
    db: Session = Depends(get_db),
):
    service = TenantAdminService(db, ctx)
    return ApiResponse(
        message="Operación completada.",
        data=service.perfil(),
    )


@router.patch("/profile", response_model=ApiResponse[TenantProfile])
def update_profile(
    data: TenantProfileUpdate,
    ctx: TenantScope,
    actor: ProfileWriter,
    db: Session = Depends(get_db),
):
    service = TenantAdminService(db, ctx)
    return ApiResponse(
        message="Perfil actualizado.",
        data=service.actualizar_perfil(data),
    )


@router.get("/support-sessions", response_model=ApiResponse[Page[SupportSessionResponse]])
def get_support_sessions(
    ctx: TenantScope,
    actor: SupportSessionReader,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    service = TenantAdminService(db, ctx)
    return ApiResponse(
        message="Operación completada.",
        data=service.accesos_soporte(page=page, page_size=page_size),
    )


@router.get("/support/requests", response_model=ApiResponse[Page[SupportSessionResponse]])
def get_support_requests(
    ctx: TenantScope,
    actor: SupportApprover,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    service = SupportService(db, actor)
    return ApiResponse(
        message="Solicitudes de soporte obtenidas.",
        data=service.listar(tenant_id=ctx.tenant_id, page=page, page_size=page_size),
    )


@router.post("/support/requests/{session_id}/approve", response_model=ApiResponse[SupportSessionResponse])
def approve_support_request(
    session_id: UUID,
    data: SupportApprovalRequest,
    ctx: TenantScope,
    actor: SupportApprover,
    db: Session = Depends(get_db),
):
    service = SupportService(db, actor)
    return ApiResponse(
        message="Solicitud de soporte aprobada.",
        data=service.aprobar(session_id=session_id, actor_empresa=actor, minutes=data.minutes),
    )


@router.post("/support/requests/{session_id}/reject", response_model=ApiResponse[SupportSessionResponse])
def reject_support_request(
    session_id: UUID,
    data: SupportRejectionRequest,
    ctx: TenantScope,
    actor: SupportApprover,
    db: Session = Depends(get_db),
):
    service = SupportService(db, actor)
    return ApiResponse(
        message="Solicitud de soporte rechazada.",
        data=service.rechazar(session_id=session_id, actor_empresa=actor, reason=data.reason),
    )


@router.get("/support/policy", response_model=ApiResponse[dict])
def get_support_policy(
    ctx: TenantScope,
    actor: SupportApprover,
    db: Session = Depends(get_db),
):
    service = SupportService(db, actor)
    return ApiResponse(
        message="Política de acceso de soporte obtenida.",
        data=service.obtener_politica(tenant_id=ctx.tenant_id),
    )


@router.put("/support/policy", response_model=ApiResponse[dict])
def update_support_policy(
    data: SupportPolicyUpdate,
    ctx: TenantScope,
    actor: SupportApprover,
    db: Session = Depends(get_db),
):
    service = SupportService(db, actor)
    return ApiResponse(
        message="Política de acceso de soporte actualizada.",
        data=service.actualizar_politica(tenant_id=ctx.tenant_id, mode=data.mode),
    )
