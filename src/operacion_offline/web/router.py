from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.infrastructure.database.session import get_db
from src.infrastructure.security.tenancy import TenantContext, require_feature
from src.operacion_offline.application.snapshot_service import SnapshotService
from src.operacion_offline.web.schemas import OfflineSnapshot
from src.shared.responses.api_response import ApiResponse

router = APIRouter(prefix="/offline", tags=["PAQ-07 · Operación sin conexión"])


@router.get("/snapshot", response_model=ApiResponse[OfflineSnapshot])
def snapshot(branch_id: UUID | None = None, since: datetime | None = None,
             ctx: TenantContext = Depends(require_feature("offline")), db: Session = Depends(get_db)):
    return ApiResponse(message="Instantánea preparada.", data=SnapshotService(db, ctx).generar(branch_id, since))
