from typing import Annotated, Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.infrastructure.security.tenancy import TenantScope, get_tenant_context
from src.analitica_ml.application.dashboard_service import DashboardMLService
from src.analitica_ml.application.entrenamiento_service import EntrenamientoService
from src.analitica_ml.infrastructure.models import MLModelModel, MLTrainingRunModel
from src.analitica_ml.web.schemas import (
    AnomalyOut,
    CustomerSegmentOut,
    MLDashboardOut,
    MLTrainingRunOut,
    ResolveAnomalyIn,
)
from src.shared.responses.api_response import ApiResponse

router = APIRouter(prefix="/analytics/ml", tags=["PAQ-10 · Analítica y Machine Learning"])

TenantCtx = Annotated[TenantScope, Depends(get_tenant_context)]
CurrentUser = Annotated[UserModel, Depends(get_current_user)]


@router.get("/dashboard", response_model=ApiResponse[MLDashboardOut])
def get_ml_dashboard(
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("ml_dashboard.read")),
) -> ApiResponse[MLDashboardOut]:
    svc = DashboardMLService(db)
    data = svc.obtener_tablero(ctx.tenant_id)
    return ApiResponse(message="Tablero ML obtenido.", data=data)


@router.get("/segments", response_model=ApiResponse[List[CustomerSegmentOut]])
def get_customer_segments(
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("ml_dashboard.read")),
) -> ApiResponse[List[CustomerSegmentOut]]:
    svc = DashboardMLService(db)
    items = svc.listar_segmentos(ctx.tenant_id)
    return ApiResponse(message="Segmentos de clientes obtenidos.", data=items)


@router.get("/anomalies", response_model=ApiResponse[List[AnomalyOut]])
def get_anomalies(
    ctx: TenantCtx,
    user: CurrentUser,
    resolved: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("ml_dashboard.read")),
) -> ApiResponse[List[AnomalyOut]]:
    svc = DashboardMLService(db)
    items = svc.listar_anomalias(ctx.tenant_id, resueltas=resolved)
    return ApiResponse(message="Anomalías obtenidas.", data=items)


@router.post("/anomalies/{anomaly_id}/resolve", response_model=ApiResponse[Dict[str, Any]])
def resolve_anomaly(
    anomaly_id: str,
    payload: ResolveAnomalyIn,
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("ml_models.manage")),
) -> ApiResponse[Dict[str, Any]]:
    svc = DashboardMLService(db)
    res = svc.resolver_anomalia(ctx.tenant_id, anomaly_id, payload.notes)
    return ApiResponse(message="Anomalía resuelta correctamente.", data=res)


@router.post("/initialize", response_model=ApiResponse[Dict[str, Any]], status_code=status.HTTP_200_OK)
def initialize_ml_models(
    ctx: TenantCtx,
    user: CurrentUser,
    seed: int = Query(42),
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("ml_models.manage")),
) -> ApiResponse[Dict[str, Any]]:
    svc = EntrenamientoService(db)
    summary = svc.inicializar_datos_y_modelos(ctx.tenant_id, seed=seed)
    return ApiResponse(message="Modelos y datos inicializados.", data=summary)


# Rutas para administración de modelos
platform_ml_router = APIRouter(prefix="/platform/ml", tags=["PAQ-10 · Plataforma ML"])


@platform_ml_router.get("/runs", response_model=ApiResponse[List[MLTrainingRunOut]])
def get_training_runs(
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("ml_models.manage")),
) -> ApiResponse[List[MLTrainingRunOut]]:
    tenant_id_str = str(ctx.tenant_id)
    runs = (
        db.query(MLTrainingRunModel)
        .filter(MLTrainingRunModel.tenant_id == tenant_id_str)
        .order_by(MLTrainingRunModel.created_at.desc())
        .limit(50)
        .all()
    )
    result = [
        MLTrainingRunOut(
            id=r.id,
            tenant_id=r.tenant_id,
            model_type=r.model_type,
            status=r.status,
            metrics=r.metrics,
            created_at=r.created_at.isoformat(),
            finished_at=r.finished_at.isoformat() if r.finished_at else None,
        )
        for r in runs
    ]
    return ApiResponse(message="Ejecuciones de entrenamiento obtenidas.", data=result)


@platform_ml_router.get("/models", response_model=ApiResponse[List[Dict[str, Any]]])
def get_models_list(
    ctx: TenantCtx,
    user: CurrentUser,
    db: Session = Depends(get_db),
    _perm: UserModel = Depends(require_permissions("ml_models.manage")),
) -> ApiResponse[List[Dict[str, Any]]]:
    tenant_id_str = str(ctx.tenant_id)
    models = (
        db.query(MLModelModel)
        .filter(MLModelModel.tenant_id == tenant_id_str)
        .order_by(MLModelModel.created_at.desc())
        .all()
    )
    return ApiResponse(
        message="Modelos obtenidos.",
        data=[
            {
                "id": m.id,
                "name": m.name,
                "model_type": m.model_type,
                "version": m.version,
                "metrics": m.metrics,
                "is_active": m.is_active,
                "created_at": m.created_at.isoformat(),
            }
            for m in models
        ],
    )
