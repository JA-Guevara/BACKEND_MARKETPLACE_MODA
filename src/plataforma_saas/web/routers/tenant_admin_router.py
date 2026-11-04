from datetime import date
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.infrastructure.security.tenancy import TenantScope
from src.plataforma_saas.application.tenant_admin_service import TenantAdminService
from src.plataforma_saas.web.schemas.support import SupportSessionResponse
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


@router.get("/dashboard", response_model=ApiResponse[TenantDashboard])
def get_dashboard(
    ctx: TenantScope,
    actor: DashboardReader,
    branch_id: UUID | None = None,
    today: date | None = None,
    db: Session = Depends(get_db),
):
    current_date = today or date.today()
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
