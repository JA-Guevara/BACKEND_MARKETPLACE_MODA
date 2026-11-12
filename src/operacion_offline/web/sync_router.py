from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.session import get_db
from src.infrastructure.security.access_context import AccessContext, get_access_context
from src.infrastructure.security.authorization import require_permissions
from src.infrastructure.security.tenancy import TenantScope, get_tenant_context
from src.operacion_offline.application.conflict_service import ConflictService
from src.operacion_offline.application.sync_service import SyncService
from src.dispositivos.application.service import DeviceService
from src.operacion_offline.infrastructure.models.sync import SyncBatchModel
from src.operacion_offline.web.sync_schemas import (
    ConflictOut,
    ConflictResolveIn,
    PurchaseResolveIn,
    RefundConfirmIn,
    SyncBatchDetailOut,
    SyncBatchIn,
    SyncBatchLogOut,
    SyncBatchOut,
    SyncResultOut,
    SyncStatusIn,
)
from src.shared.responses.api_response import ApiResponse


router = APIRouter(prefix="/sync", tags=["PAQ-07 · Operación sin conexión"])

TenantCtx = Annotated[TenantScope, Depends(get_tenant_context)]
CurrentUser = Annotated[UserModel, Depends(get_current_user)]


@router.post("/batch", response_model=ApiResponse[SyncBatchOut], status_code=status.HTTP_200_OK)
def sync_batch(
    data: SyncBatchIn,
    request: Request,
    ctx: TenantCtx,
    user: CurrentUser,
    x_device_id: str | None = Header(None, alias="X-Device-Id"),
    x_client_platform: str | None = Header(None, alias="X-Client-Platform"),
    x_client_version: str | None = Header(None, alias="X-Client-Version"),
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("sync.write")),
):
    device_id_to_check = None
    branch_id_to_check = None
    if data.operations:
        for op in data.operations:
            if hasattr(op, "device_id") and op.device_id:
                device_id_to_check = op.device_id
                branch_id_to_check = getattr(op, "branch_id", None)
                break
    if not device_id_to_check:
        device_id_to_check = x_device_id

    if device_id_to_check and ctx.tenant_id:
        DeviceService(db).verificar_y_registrar(
            tenant_id=ctx.tenant_id,
            device_id=device_id_to_check,
            platform=x_client_platform,
            app_version=x_client_version,
            user_id=user.id,
            branch_id=branch_id_to_check,
            op_type="sync",
        )
        db.commit()

    client_ip = request.client.host if request.client else None
    svc = SyncService(db, ctx)
    res = svc.procesar_lote(data, client_ip)
    return ApiResponse(message="Lote procesado exitosamente.", data=res)


@router.post("/status", response_model=ApiResponse[list[SyncResultOut]], status_code=status.HTTP_200_OK)
def sync_status(
    data: SyncStatusIn,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("sync.write")),
):
    svc = SyncService(db, ctx)
    res = svc.estado(data.client_request_ids)
    return ApiResponse(message="Estado de operaciones obtenido.", data=res)


@router.post(
    "/purchases/{client_request_id}/resolve",
    response_model=ApiResponse[SyncResultOut],
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
)
def resolve_purchase(
    client_request_id: UUID,
    data: PurchaseResolveIn,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("sync.write")),
):
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Resolución de compra pendiente de implementación (Ola 1)")


@router.get("/conflicts", response_model=ApiResponse[dict], status_code=status.HTTP_200_OK)
def list_conflicts(
    ctx: TenantCtx,
    user: CurrentUser,
    branch_id: UUID | None = None,
    status: Literal["OPEN", "RESOLVED", "ALL"] = "OPEN",
    refund_status: Literal['pending','confirmed'] | None = None,
    type: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("sync_conflicts.read")),
):
    svc = ConflictService(db, ctx, user)
    res = svc.listar(branch_id=branch_id, status=status, refund_status=refund_status, type=type, page=page, page_size=page_size)
    return ApiResponse(message="Lista de conflictos obtenida.", data=res)


@router.get("/conflicts/{conflict_id}", response_model=ApiResponse[ConflictOut], status_code=status.HTTP_200_OK)
def get_conflict(
    conflict_id: UUID,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("sync_conflicts.read")),
):
    svc = ConflictService(db, ctx, user)
    res = svc.obtener(conflict_id)
    return ApiResponse(message="Detalle de conflicto obtenido.", data=res)


@router.post("/conflicts/{conflict_id}/resolve", response_model=ApiResponse[ConflictOut], status_code=status.HTTP_200_OK)
def resolve_conflict(
    conflict_id: UUID,
    data: ConflictResolveIn,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("sync_conflicts.resolve")),
):
    svc = ConflictService(db, ctx, user)
    res = svc.resolver(conflict_id, data)
    return ApiResponse(message="Conflicto resuelto exitosamente.", data=res)


@router.get("/batches", response_model=ApiResponse[dict], status_code=status.HTTP_200_OK)
def list_batches(
    ctx: TenantCtx,
    user: CurrentUser,
    branch_id: UUID | None = None,
    device_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("sync_log.read")),
):
    query = select(SyncBatchModel).where(SyncBatchModel.tenant_id == ctx.tenant_id)
    if branch_id:
        query = query.where(SyncBatchModel.branch_id == branch_id)
    if device_id:
        query = query.where(SyncBatchModel.device_id == device_id)
    if date_from:
        query = query.where(SyncBatchModel.started_at >= date_from)
    if date_to:
        query = query.where(SyncBatchModel.started_at <= date_to)

    total = len(db.scalars(query).all())
    offset = (page - 1) * page_size
    batches = db.scalars(query.order_by(SyncBatchModel.started_at.desc()).offset(offset).limit(page_size)).all()

    items = [
        SyncBatchLogOut(
            id=b.id,
            device_id=b.device_id,
            user_name=None,
            branch_name=None,
            started_at=b.started_at,
            duration_ms=b.duration_ms,
            received=b.received,
            confirmed=b.confirmed,
            conflicts=b.conflicts,
            rejected=b.rejected,
            replays=b.replays,
            error_summary=b.error_summary,
        )
        for b in batches
    ]
    return ApiResponse(
        message="Historial de lotes obtenido.",
        data={
            "items": [i.model_dump() for i in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if page_size else 1,
        },
    )


@router.post('/conflicts/{conflict_id}/refund', response_model=ApiResponse[ConflictOut])
def confirm_conflict_refund(conflict_id: UUID, data: RefundConfirmIn, ctx: TenantCtx, user: CurrentUser,
                            db: Session = Depends(get_db),
                            _perm: UserModel = Depends(require_permissions('sync_conflicts.resolve'))):
    return ApiResponse(message='Reintegro en efectivo confirmado.', data=ConflictService(db,ctx,user).confirmar_reintegro(conflict_id,data))


@router.get("/batches/{batch_id}", response_model=ApiResponse[SyncBatchDetailOut], status_code=status.HTTP_200_OK)
def get_batch_detail(
    batch_id: UUID,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("sync_log.read")),
):
    svc = SyncService(db, ctx)
    res = svc.detalle_lote(batch_id)
    return ApiResponse(message="Detalle de lote obtenido.", data=res)
