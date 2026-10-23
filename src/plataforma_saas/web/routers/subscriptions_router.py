from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions, require_platform_permissions
from src.infrastructure.security.tenancy import TenantScope
from src.plataforma_saas.application.subscription_service import SubscriptionService
from src.plataforma_saas.web.schemas.subscriptions import ChangePlanRequest, RenewRequest, StatusChangeRequest, SubscriptionDetail
from src.shared.responses.api_response import ApiResponse

platform_router = APIRouter(prefix="/platform/tenants/{tenant_id}/subscription", tags=["PAQ-06 · Plataforma SaaS"])
tenant_router = APIRouter(prefix="/tenant/subscription", tags=["PAQ-06 · Plataforma SaaS"])
Reader = Annotated[UserModel, Depends(require_platform_permissions("subscriptions.read"))]
Writer = Annotated[UserModel, Depends(require_platform_permissions("subscriptions.write"))]
TenantReader = Annotated[UserModel, Depends(require_permissions("my_subscription.read"))]


@platform_router.get("", response_model=ApiResponse[SubscriptionDetail])
def subscription(tenant_id: UUID, actor: Reader, db: Session = Depends(get_db)):
    return ApiResponse(message="Operación completada.", data=SubscriptionService(db, actor).detalle(tenant_id))


@platform_router.post("/change-plan", response_model=ApiResponse[SubscriptionDetail])
def change_plan(tenant_id: UUID, data: ChangePlanRequest, actor: Writer, db: Session = Depends(get_db)):
    return ApiResponse(message="Operación completada.", data=SubscriptionService(db, actor).cambiar_plan(tenant_id, data))


@platform_router.post("/renew", response_model=ApiResponse[SubscriptionDetail])
def renew(tenant_id: UUID, data: RenewRequest, actor: Writer, db: Session = Depends(get_db)):
    return ApiResponse(message="Operación completada.", data=SubscriptionService(db, actor).renovar(tenant_id, data))


@platform_router.post("/status", response_model=ApiResponse[SubscriptionDetail])
def change_status(tenant_id: UUID, data: StatusChangeRequest, actor: Writer, db: Session = Depends(get_db)):
    return ApiResponse(message="Operación completada.", data=SubscriptionService(db, actor).cambiar_estado(tenant_id, data))


@tenant_router.get("", response_model=ApiResponse[SubscriptionDetail])
def my_subscription(ctx: TenantScope, actor: TenantReader, db: Session = Depends(get_db)):
    return ApiResponse(message="Operación completada.", data=SubscriptionService(db, actor).detalle(ctx.tenant_id))
