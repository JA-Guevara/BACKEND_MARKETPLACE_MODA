from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_platform_permissions
from src.plataforma_saas.application.tenant_service import TenantService
from src.plataforma_saas.web.schemas.tenants import TenantCreate, TenantUpdate, TenantStatusChange, TenantResponse, TenantStats, ActivityItem
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page

router = APIRouter(prefix="/platform/tenants", tags=["PAQ-06 · Plataforma SaaS"])
Reader = Annotated[UserModel, Depends(require_platform_permissions("tenants.read"))]
Writer = Annotated[UserModel, Depends(require_platform_permissions("tenants.write"))]


@router.get("", response_model=ApiResponse[Page[TenantResponse]])
def list_tenants(actor: Reader, db: Session = Depends(get_db), search: str | None = None, status: str | None = None,
                 plan_code: str | None = None, subscription_status: str | None = None, expiring_7d: bool = False,
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    return ApiResponse(message="Operación completada.", data=TenantService(db, actor).listar(search=search, status=status, plan_code=plan_code,
        page=page, page_size=page_size, subscription_status=subscription_status, expiring_7d=expiring_7d))


@router.get("/stats", response_model=ApiResponse[TenantStats])
def tenant_stats(actor: Reader, db: Session = Depends(get_db)):
    return ApiResponse(message="Operación completada.", data=TenantService(db, actor).estadisticas())


@router.get("/{tenant_id}", response_model=ApiResponse[TenantResponse])
def get_tenant(tenant_id: UUID, actor: Reader, db: Session = Depends(get_db)):
    return ApiResponse(message="Operación completada.", data=TenantService(db, actor).obtener(tenant_id))


@router.get("/{tenant_id}/activity", response_model=ApiResponse[list[ActivityItem]])
def tenant_activity(tenant_id: UUID, actor: Reader, db: Session = Depends(get_db)):
    return ApiResponse(message="Operación completada.", data=TenantService(db, actor).actividad(tenant_id))


@router.post("", status_code=201, response_model=ApiResponse[TenantResponse])
def create_tenant(data: TenantCreate, actor: Writer, db: Session = Depends(get_db)):
    service = TenantService(db, actor)
    tenant = service.registrar(data)
    return ApiResponse(message="Empresa registrada. El administrador debe activar su cuenta con el enlace de invitación.", data=service.obtener(tenant.id))


@router.patch("/{tenant_id}", response_model=ApiResponse[TenantResponse])
def update_tenant(tenant_id: UUID, data: TenantUpdate, actor: Writer, db: Session = Depends(get_db)):
    service = TenantService(db, actor)
    service.actualizar(tenant_id, data)
    return ApiResponse(message="Operación completada.", data=service.obtener(tenant_id))


@router.post("/{tenant_id}/deactivate", response_model=ApiResponse[TenantResponse])
def deactivate_tenant(tenant_id: UUID, data: TenantStatusChange, actor: Writer, db: Session = Depends(get_db)):
    service = TenantService(db, actor)
    service.desactivar(tenant_id, data.reason)
    return ApiResponse(message="Operación completada.", data=service.obtener(tenant_id))


@router.post("/{tenant_id}/activate", response_model=ApiResponse[TenantResponse])
def activate_tenant(tenant_id: UUID, actor: Writer, db: Session = Depends(get_db)):
    service = TenantService(db, actor)
    service.activar(tenant_id)
    return ApiResponse(message="Operación completada.", data=service.obtener(tenant_id))


@router.post("/{tenant_id}/resend-invitation", response_model=ApiResponse[None])
def resend_invitation(tenant_id: UUID, actor: Writer, db: Session = Depends(get_db)):
    delivered = TenantService(db, actor).reenviar_invitacion(tenant_id)
    return ApiResponse(message="Enlace de activación enviado." if delivered else "No se pudo enviar el correo. La empresa sigue registrada; puedes reintentar.")
