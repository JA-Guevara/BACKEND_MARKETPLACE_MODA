from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_platform_permissions
from src.plataforma_saas.application.plan_service import PlanService
from src.plataforma_saas.web.schemas.plans import PlanCreate, PlanUpdate, PlanResponse, PlanSaveResult, FeatureCatalogItem
from src.shared.responses.api_response import ApiResponse

router = APIRouter(prefix="/platform/plans", tags=["PAQ-06 · Plataforma SaaS"])
Reader = Annotated[UserModel, Depends(require_platform_permissions("plans.read"))]
Writer = Annotated[UserModel, Depends(require_platform_permissions("plans.write"))]


@router.get("", response_model=ApiResponse[list[PlanResponse]])
def list_plans(actor: Reader, include_inactive: bool = False, db: Session = Depends(get_db)):
    return ApiResponse(message="Operación completada.", data=PlanService(db, actor).listar(include_inactive))


@router.get("/features", response_model=ApiResponse[list[FeatureCatalogItem]])
def feature_catalog(actor: Reader, db: Session = Depends(get_db)):
    return ApiResponse(message="Operación completada.", data=PlanService(db, actor).catalogo())


@router.post("", status_code=201, response_model=ApiResponse[PlanSaveResult])
def create_plan(data: PlanCreate, actor: Writer, db: Session = Depends(get_db)):
    return ApiResponse(message="Operación completada.", data=PlanService(db, actor).crear(data))


@router.patch("/{plan_id}", response_model=ApiResponse[PlanSaveResult])
def update_plan(plan_id: UUID, data: PlanUpdate, actor: Writer, db: Session = Depends(get_db)):
    return ApiResponse(message="Operación completada.", data=PlanService(db, actor).actualizar(plan_id, data))


@router.post("/{plan_id}/deactivate", response_model=ApiResponse[PlanResponse])
def deactivate_plan(plan_id: UUID, actor: Writer, db: Session = Depends(get_db)):
    return ApiResponse(message="Operación completada.", data=PlanService(db, actor).desactivar(plan_id))


@router.post("/{plan_id}/activate", response_model=ApiResponse[PlanResponse])
def activate_plan(plan_id: UUID, actor: Writer, db: Session = Depends(get_db)):
    return ApiResponse(message="Operación completada.", data=PlanService(db, actor).activar(plan_id))
