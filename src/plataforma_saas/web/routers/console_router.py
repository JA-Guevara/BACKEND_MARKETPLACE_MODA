from datetime import date
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_platform_permissions
from src.plataforma_saas.application.console_service import ConsoleService
from src.plataforma_saas.web.schemas.console import (
    BranchSummary,
    GlobalUserResponse,
    PlatformDashboard,
    TenantOverview,
    PlatformIntelligence,
)
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page

router = APIRouter(prefix="/platform", tags=["PAQ-06 · Consola SaaS"])
Reader = Annotated[UserModel, Depends(require_platform_permissions("tenants.read"))]


@router.get("/dashboard", response_model=ApiResponse[PlatformDashboard])
def get_dashboard(
    actor: Reader,
    db: Session = Depends(get_db),
    today: date | None = None,
):
    current_date = today or date.today()
    service = ConsoleService(db)
    return ApiResponse(
        message="Operación completada.",
        data=service.tablero(current_date),
    )


@router.get("/tenants/{tenant_id}/overview", response_model=ApiResponse[TenantOverview])
def get_tenant_overview(
    tenant_id: UUID,
    actor: Reader,
    db: Session = Depends(get_db),
    today: date | None = None,
):
    current_date = today or date.today()
    service = ConsoleService(db)
    return ApiResponse(
        message="Operación completada.",
        data=service.resumen_empresa(tenant_id, current_date),
    )


@router.get(
    "/tenants/{tenant_id}/users",
    response_model=ApiResponse[Page[GlobalUserResponse]],
)
def get_tenant_users(
    tenant_id: UUID,
    actor: Reader,
    db: Session = Depends(get_db),
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    service = ConsoleService(db)
    return ApiResponse(
        message="Operación completada.",
        data=service.usuarios_empresa(tenant_id, search=search, page=page, page_size=page_size),
    )


@router.get(
    "/tenants/{tenant_id}/branches",
    response_model=ApiResponse[list[BranchSummary]],
)
def get_tenant_branches(
    tenant_id: UUID,
    actor: Reader,
    db: Session = Depends(get_db),
):
    service = ConsoleService(db)
    return ApiResponse(
        message="Operación completada.",
        data=service.sucursales_empresa(tenant_id),
    )

@router.get("/intelligence", response_model=ApiResponse[PlatformIntelligence])
def get_platform_intelligence(
    actor: Reader,
    db: Session = Depends(get_db),
    today: date | None = None,
):
    current_date = today or date.today()
    service = ConsoleService(db)
    return ApiResponse(
        message="Inteligencia de plataforma obtenida.",
        data=service.inteligencia_plataforma(current_date),
    )
