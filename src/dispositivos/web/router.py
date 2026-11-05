import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.dispositivos.application.service import DeviceService
from src.dispositivos.web.schemas import DeviceBlockIn, DeviceDetailOut, DeviceOut, DeviceUnblockIn, DeviceUpdateIn
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.infrastructure.security.tenancy import TenantScope
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page

router = APIRouter(prefix="/tenant/devices", tags=["dispositivos"])

DeviceReader = Annotated[UserModel, Depends(require_permissions("devices.read"))]
DeviceWriter = Annotated[UserModel, Depends(require_permissions("devices.write"))]


@router.get("", response_model=ApiResponse[Page[DeviceOut]])
def list_devices(
    ctx: TenantScope,
    actor: DeviceReader,
    db: Session = Depends(get_db),
    platform: str | None = None,
    status: str | None = None,
    branch_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    search: str | None = None,
    stale: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    if not ctx.tenant_id:
        raise HTTPException(status_code=400, detail={"error": "tenant_required", "message": "Se requiere contexto de empresa"})
    result = DeviceService(db).listar(
        tenant_id=ctx.tenant_id,
        platform=platform,
        status=status,
        branch_id=branch_id,
        user_id=user_id,
        search=search,
        stale=stale,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(message="Dispositivos obtenidos.", data=result)


@router.get("/export.csv")
def export_devices_csv(
    ctx: TenantScope,
    actor: DeviceReader,
    db: Session = Depends(get_db),
):
    if not ctx.tenant_id:
        raise HTTPException(status_code=400, detail={"error": "tenant_required", "message": "Se requiere contexto de empresa"})
    content = DeviceService(db).exportar_csv(ctx.tenant_id)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="dispositivos.csv"'},
    )


@router.get("/{device_id}", response_model=ApiResponse[DeviceDetailOut])
def get_device(
    device_id: uuid.UUID,
    ctx: TenantScope,
    actor: DeviceReader,
    db: Session = Depends(get_db),
):
    if not ctx.tenant_id:
        raise HTTPException(status_code=400, detail={"error": "tenant_required", "message": "Se requiere contexto de empresa"})
    result = DeviceService(db).obtener(ctx.tenant_id, device_id)
    return ApiResponse(message="Dispositivo obtenido.", data=result)


@router.post("/{device_id}/block", response_model=ApiResponse[DeviceDetailOut])
def block_device(
    device_id: uuid.UUID,
    payload: DeviceBlockIn,
    ctx: TenantScope,
    actor: DeviceWriter,
    db: Session = Depends(get_db),
):
    if not ctx.tenant_id:
        raise HTTPException(status_code=400, detail={"error": "tenant_required", "message": "Se requiere contexto de empresa"})
    result = DeviceService(db).bloquear(
        tenant_id=ctx.tenant_id,
        device_pk=device_id,
        actor_id=actor.id,
        reason=payload.reason,
        revoke_sessions=payload.revoke_sessions,
    )
    db.commit()
    return ApiResponse(message="Dispositivo bloqueado exitosamente.", data=result)


@router.post("/{device_id}/unblock", response_model=ApiResponse[DeviceDetailOut])
def unblock_device(
    device_id: uuid.UUID,
    payload: DeviceUnblockIn,
    ctx: TenantScope,
    actor: DeviceWriter,
    db: Session = Depends(get_db),
):
    if not ctx.tenant_id:
        raise HTTPException(status_code=400, detail={"error": "tenant_required", "message": "Se requiere contexto de empresa"})
    result = DeviceService(db).desbloquear(
        tenant_id=ctx.tenant_id,
        device_pk=device_id,
        actor_id=actor.id,
        reason=payload.reason,
    )
    db.commit()
    return ApiResponse(message="Dispositivo reactivado exitosamente.", data=result)


@router.patch("/{device_id}", response_model=ApiResponse[DeviceDetailOut])
def update_device(
    device_id: uuid.UUID,
    payload: DeviceUpdateIn,
    ctx: TenantScope,
    actor: DeviceWriter,
    db: Session = Depends(get_db),
):
    if not ctx.tenant_id:
        raise HTTPException(status_code=400, detail={"error": "tenant_required", "message": "Se requiere contexto de empresa"})
    result = DeviceService(db).renombrar(
        tenant_id=ctx.tenant_id,
        device_pk=device_id,
        actor_id=actor.id,
        label=payload.label,
    )
    db.commit()
    return ApiResponse(message="Dispositivo actualizado.", data=result)
