from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from src.dispositivos.application.service import DeviceService
from src.infrastructure.database.session import get_db
from src.infrastructure.security.tenancy import TenantContext, require_feature
from src.operacion_offline.application.snapshot_service import SnapshotService
from src.operacion_offline.web.schemas import OfflineSnapshot
from src.shared.responses.api_response import ApiResponse

router = APIRouter(prefix="/offline", tags=["PAQ-07 · Operación sin conexión"])


@router.get("/ping")
def ping() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/snapshot", response_model=ApiResponse[OfflineSnapshot])
def snapshot(
    branch_id: UUID | None = None,
    since: datetime | None = None,
    x_device_id: str | None = Header(None, alias="X-Device-Id"),
    x_client_platform: str | None = Header(None, alias="X-Client-Platform"),
    x_client_version: str | None = Header(None, alias="X-Client-Version"),
    ctx: TenantContext = Depends(require_feature("offline")),
    db: Session = Depends(get_db),
):
    if x_device_id and ctx.tenant_id:
        DeviceService(db).verificar_y_registrar(
            tenant_id=ctx.tenant_id,
            device_id=x_device_id,
            platform=x_client_platform,
            app_version=x_client_version,
            user_id=ctx.user.id if ctx.user else None,
            branch_id=branch_id,
            op_type="snapshot",
        )
        db.commit()
    return ApiResponse(message="Instantánea preparada.", data=SnapshotService(db, ctx).generar(branch_id, since))
