from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.infrastructure.security.tenancy import TenantScope, get_tenant_context, require_feature
from src.integraciones.application.api_keys_service import ApiKeysService
from src.integraciones.application.webhooks_service import WebhooksService
from src.integraciones.infrastructure.models import (
    ApiKeyModel,
    WebhookDeliveryModel,
    WebhookEndpointModel,
)
from src.shared.exceptions.domain_exception import NotFoundError
from src.shared.responses.api_response import ApiResponse


router = APIRouter(
    prefix="/tenant/integrations",
    tags=["PAQ-06 · Integraciones"],
    dependencies=[Depends(require_feature("integrations"))],
)

TenantCtx = Annotated[TenantScope, Depends(get_tenant_context)]
CurrentUser = Annotated[UserModel, Depends(get_current_user)]


# --- Schemas ---
class ApiKeyCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: ["sales.read", "stock.read", "catalog.read"])


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyCreatedOut(ApiKeyOut):
    raw_key: str


class WebhookEndpointCreateIn(BaseModel):
    url: str = Field(min_length=5, max_length=500)
    events: list[str] = Field(default_factory=lambda: ["*"])


class WebhookEndpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    events: list[str]
    is_active: bool
    created_at: datetime


class WebhookEndpointCreatedOut(WebhookEndpointOut):
    secret: str


class WebhookDeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    endpoint_id: UUID
    event_id: UUID
    attempt: int
    status_code: int | None = None
    status: str
    next_retry_at: datetime | None = None
    delivered_at: datetime | None = None
    error: str | None = None
    created_at: datetime


# --- API Keys Endpoints ---
@router.get("/api-keys", response_model=ApiResponse[list[ApiKeyOut]])
def list_api_keys(
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("integrations.read")),
) -> ApiResponse[list[ApiKeyOut]]:
    keys = ApiKeysService(db).listar(ctx.tenant_id)
    return ApiResponse(message="Claves de API listadas.", data=[ApiKeyOut.model_validate(k) for k in keys])


@router.post("/api-keys", response_model=ApiResponse[ApiKeyCreatedOut], status_code=status.HTTP_201_CREATED)
def create_api_key(
    data: ApiKeyCreateIn,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("integrations.write")),
) -> ApiResponse[ApiKeyCreatedOut]:
    key_model, raw_key = ApiKeysService(db).crear(
        tenant_id=ctx.tenant_id,
        name=data.name,
        scopes=data.scopes,
        created_by=user.id,
    )
    result = ApiKeyCreatedOut(
        id=key_model.id,
        name=key_model.name,
        prefix=key_model.prefix,
        scopes=key_model.scopes,
        created_at=key_model.created_at,
        last_used_at=key_model.last_used_at,
        revoked_at=key_model.revoked_at,
        raw_key=raw_key,
    )
    return ApiResponse(message="Clave de API creada. Guárdela ahora; no se volverá a mostrar.", data=result)


@router.delete("/api-keys/{id}", response_model=ApiResponse[None])
def revoke_api_key(
    id: UUID,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("integrations.write")),
) -> ApiResponse[None]:
    revoked = ApiKeysService(db).revocar(ctx.tenant_id, id)
    if not revoked:
        raise NotFoundError("Clave de API no encontrada o ya revocada.")
    return ApiResponse(message="Clave de API revocada.")


# --- Webhooks Endpoints ---
@router.get("/webhooks", response_model=ApiResponse[list[WebhookEndpointOut]])
def list_webhook_endpoints(
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("integrations.read")),
) -> ApiResponse[list[WebhookEndpointOut]]:
    endpoints = WebhooksService(db).listar_endpoints(ctx.tenant_id)
    return ApiResponse(message="Endpoints listados.", data=[WebhookEndpointOut.model_validate(e) for e in endpoints])


@router.post("/webhooks", response_model=ApiResponse[WebhookEndpointCreatedOut], status_code=status.HTTP_201_CREATED)
def create_webhook_endpoint(
    data: WebhookEndpointCreateIn,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("integrations.write")),
) -> ApiResponse[WebhookEndpointCreatedOut]:
    endpoint, secret = WebhooksService(db).crear_endpoint(
        tenant_id=ctx.tenant_id,
        url=data.url,
        events=data.events,
        created_by=user.id,
    )
    result = WebhookEndpointCreatedOut(
        id=endpoint.id,
        url=endpoint.url,
        events=endpoint.events,
        is_active=endpoint.is_active,
        created_at=endpoint.created_at,
        secret=secret,
    )
    return ApiResponse(message="Endpoint de webhook creado. Conserve el secreto para validar la firma HMAC.", data=result)


@router.delete("/webhooks/{id}", response_model=ApiResponse[None])
def delete_webhook_endpoint(
    id: UUID,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("integrations.write")),
) -> ApiResponse[None]:
    deleted = WebhooksService(db).eliminar_endpoint(ctx.tenant_id, id)
    if not deleted:
        raise NotFoundError("Endpoint de webhook no encontrado.")
    return ApiResponse(message="Endpoint eliminado.")


@router.post("/webhooks/{id}/test", response_model=ApiResponse[WebhookDeliveryOut])
def test_webhook_endpoint(
    id: UUID,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("integrations.write")),
) -> ApiResponse[WebhookDeliveryOut]:
    delivery = WebhooksService(db).test_endpoint(ctx.tenant_id, id)
    return ApiResponse(message="Prueba de webhook despachada.", data=WebhookDeliveryOut.model_validate(delivery))


@router.get("/webhooks/deliveries", response_model=ApiResponse[list[WebhookDeliveryOut]])
def list_deliveries(
    ctx: TenantCtx,
    user: CurrentUser,
    endpoint_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("integrations.read")),
) -> ApiResponse[list[WebhookDeliveryOut]]:
    stmt = (
        select(WebhookDeliveryModel)
        .join(WebhookEndpointModel)
        .where(WebhookEndpointModel.tenant_id == ctx.tenant_id)
        .order_by(WebhookDeliveryModel.created_at.desc())
        .limit(limit)
    )
    if endpoint_id:
        stmt = stmt.where(WebhookDeliveryModel.endpoint_id == endpoint_id)

    deliveries = list(db.scalars(stmt).all())
    return ApiResponse(message="Entregas obtenidas.", data=[WebhookDeliveryOut.model_validate(d) for d in deliveries])


@router.post("/webhooks/deliveries/{id}/redeliver", response_model=ApiResponse[WebhookDeliveryOut])
def redeliver_webhook(
    id: UUID,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("integrations.write")),
) -> ApiResponse[WebhookDeliveryOut]:
    delivery = WebhooksService(db).redeliver(ctx.tenant_id, id)
    return ApiResponse(message="Entrega reenviada para reintento.", data=WebhookDeliveryOut.model_validate(delivery))
