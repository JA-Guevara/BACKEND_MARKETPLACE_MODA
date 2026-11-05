from typing import Annotated, Any, Optional
from fastapi import APIRouter, Depends, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.infrastructure.security.tenancy import TenantScope, get_tenant_context, require_feature
from src.reportes_ia.application.reportes_ia_service import ReportesIAService
from src.reportes_ia.web.schemas import (
    DefinitionOut,
    ExportIn,
    HistoryResponse,
    InterpretIn,
    ReportResponse,
    RunIn,
)
from src.shared.responses.api_response import ApiResponse

router = APIRouter(
    prefix="/analytics/ai-reports",
    tags=["PAQ-05 · Reportes inteligentes con IA"],
    dependencies=[Depends(require_feature("ai_reports"))],
)

TenantCtx = Annotated[TenantScope, Depends(get_tenant_context)]
CurrentUser = Annotated[UserModel, Depends(get_current_user)]


@router.get("/definitions", response_model=ApiResponse[list[DefinitionOut]])
def get_definitions(
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("ai_reports.use")),
) -> ApiResponse[list[DefinitionOut]]:
    svc = ReportesIAService(db, ctx.tenant_id, user.id)
    defs = svc.obtener_definiciones()
    return ApiResponse(message="Definiciones de reportes obtenidas.", data=defs)


@router.post("/interpret", response_model=ApiResponse[dict[str, Any]])
def interpret_report_prompt(
    data: InterpretIn,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("ai_reports.use")),
) -> ApiResponse[dict[str, Any]]:
    svc = ReportesIAService(db, ctx.tenant_id, user.id)
    result = svc.interpretar(data.text, data.channel)
    return ApiResponse(message="Consulta interpretada.", data=result)


@router.post("/run", response_model=ApiResponse[ReportResponse])
def run_report(
    data: RunIn,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("ai_reports.use")),
) -> ApiResponse[ReportResponse]:
    svc = ReportesIAService(db, ctx.tenant_id, user.id)
    report = svc.ejecutar(data.spec, data.request_id)
    return ApiResponse(message="Reporte ejecutado.", data=jsonable_encoder(report))


@router.post("/export")
def export_report(
    data: ExportIn,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("ai_reports.use")),
):
    svc = ReportesIAService(db, ctx.tenant_id, user.id)
    content, filename, media_type = svc.exportar(data.spec, data.format, data.request_id)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Access-Control-Expose-Headers": "Content-Disposition",
    }
    return StreamingResponse(iter([content]), media_type=media_type, headers=headers)


@router.get("/history", response_model=ApiResponse[HistoryResponse])
def get_report_history(
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    mine: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _perm: UserModel = Depends(require_permissions("ai_reports.use")),
) -> ApiResponse[HistoryResponse]:
    svc = ReportesIAService(db, ctx.tenant_id, user.id)

    # Si tiene el permiso ai_reports.history puede ver toda la empresa, salvo que pida explícitamente mine=True
    tiene_permiso_empresa = any(p.code == "ai_reports.history" for r in user.roles for p in r.permissions)
    solo_mios = mine or (not tiene_permiso_empresa)

    hist = svc.historial(solo_mios=solo_mios, page=page, page_size=page_size)
    return ApiResponse(message="Historial obtenido.", data=hist)
