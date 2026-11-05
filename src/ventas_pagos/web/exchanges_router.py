from typing import Annotated, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.infrastructure.security.tenancy import TenantScope, get_tenant_context
from src.shared.responses.api_response import ApiResponse
from src.ventas_pagos.application.exchange_service import ExchangeService
from src.ventas_pagos.web.exchange_schemas import (
    ExchangeCalculateIn,
    ExchangeCalculateOut,
    ExchangeDetailOut,
    ExchangeListOut,
    ExchangeOrderLookupOut,
    ExchangePolicyIn,
    ExchangePolicyOut,
    ExecuteExchangeIn,
)

router = APIRouter(prefix="/commerce/admin/exchanges", tags=["PAQ-04 · Cambios de prenda"])

TenantCtx = Annotated[TenantScope, Depends(get_tenant_context)]
CurrentUser = Annotated[UserModel, Depends(get_current_user)]


@router.get("/policy", response_model=ApiResponse[ExchangePolicyOut])
def get_exchange_policy(
    ctx: TenantCtx,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("exchanges.read")),
) -> ApiResponse[ExchangePolicyOut]:
    svc = ExchangeService(db)
    data = svc.obtener_politica(ctx.tenant_id)
    return ApiResponse(message="Política de plazo de cambio obtenida.", data=data)


@router.put("/policy", response_model=ApiResponse[ExchangePolicyOut])
def update_exchange_policy(
    body: ExchangePolicyIn,
    ctx: TenantCtx,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("exchanges.write")),
) -> ApiResponse[ExchangePolicyOut]:
    svc = ExchangeService(db)
    data = svc.actualizar_politica(ctx.tenant_id, body.exchange_days)
    return ApiResponse(message="Política de plazo de cambio actualizada.", data=data)


@router.get("/lookup/{order_id_or_number}", response_model=ApiResponse[ExchangeOrderLookupOut])
def lookup_order_for_exchange(
    order_id_or_number: str,
    ctx: TenantCtx,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("exchanges.read")),
) -> ApiResponse[ExchangeOrderLookupOut]:
    svc = ExchangeService(db)
    data = svc.buscar_orden_para_cambio(ctx.tenant_id, order_id_or_number)
    return ApiResponse(message="Pedido consultado para cambio.", data=data)


@router.post("/calculate", response_model=ApiResponse[ExchangeCalculateOut])
def calculate_exchange(
    body: ExchangeCalculateIn,
    ctx: TenantCtx,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("exchanges.read")),
) -> ApiResponse[ExchangeCalculateOut]:
    svc = ExchangeService(db)
    res = svc.calcular_cambio(ctx.tenant_id, body.branch_id, [line.model_dump() for line in body.lines])
    data = {
        "total_returned_value": res.total_returned_value,
        "total_delivered_value": res.total_delivered_value,
        "difference_amount": res.difference_amount,
        "tipo_diferencia": res.tipo_diferencia,
        "lineas": [
            {
                "original_variant_id": str(l.original_variant_id),
                "returned_quantity": l.returned_quantity,
                "returned_value": l.returned_value,
                "new_variant_id": str(l.new_variant_id),
                "delivered_quantity": l.delivered_quantity,
                "delivered_value": l.delivered_value,
                "difference": l.difference,
            }
            for l in res.lineas
        ],
    }
    return ApiResponse(message="Diferencia de cambio calculada.", data=data)


@router.post("", response_model=ApiResponse[ExchangeDetailOut], status_code=status.HTTP_201_CREATED)
def execute_exchange(
    body: ExecuteExchangeIn,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("exchanges.write")),
) -> ApiResponse[ExchangeDetailOut]:
    svc = ExchangeService(db)
    payload = body.model_dump()
    payload["actor_email"] = user.email
    data = svc.ejecutar_cambio(ctx.tenant_id, body.branch_id, user.id, payload)
    return ApiResponse(message="Cambio de prenda realizado con éxito.", data=data)


@router.get("", response_model=ApiResponse[ExchangeListOut])
def list_exchanges(
    ctx: TenantCtx,
    branch_id: Optional[UUID] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("exchanges.read")),
) -> ApiResponse[ExchangeListOut]:
    svc = ExchangeService(db)
    data = svc.listar_cambios(ctx.tenant_id, branch_id, page, page_size)
    return ApiResponse(message="Historial de cambios obtenido.", data=data)


@router.get("/{exchange_id}", response_model=ApiResponse[ExchangeDetailOut])
def get_exchange_detail(
    exchange_id: UUID,
    ctx: TenantCtx,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("exchanges.read")),
) -> ApiResponse[ExchangeDetailOut]:
    svc = ExchangeService(db)
    data = svc.obtener_cambio(ctx.tenant_id, exchange_id)
    return ApiResponse(message="Detalle de cambio obtenido.", data=data)
