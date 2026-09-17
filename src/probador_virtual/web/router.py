import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.probador_virtual.application.use_cases.iniciar_experiencia import IniciarExperiencia
from src.probador_virtual.application.use_cases.preparar_prenda import PrepararPrenda
from src.probador_virtual.infrastructure.http.schemas import (
    AjustarRecursoRequest,
    ExperienciaVirtualResponse,
    IniciarExperienciaRequest,
    PrepararRecursoRequest,
    RecursoTryOnResponse,
)
from src.probador_virtual.infrastructure.persistence.models.recurso_tryon import (
    ESTADO_MANUAL,
    TryOnAssetModel,
)
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError
from src.shared.responses.api_response import ApiResponse

router = APIRouter(prefix="/vestidor", tags=["vestidor virtual"])
User = Annotated[UserModel, Depends(get_current_user)]
# La preparación es gestión de catálogo: se apoya en el permiso existente.
CatalogWriter = Annotated[UserModel, Depends(require_permissions("catalog.write"))]
CatalogReader = Annotated[UserModel, Depends(require_permissions("catalog.read"))]


@router.post("/sessions", response_model=ApiResponse[ExperienciaVirtualResponse])
def start_session(data: IniciarExperienciaRequest, user: User, db: Session = Depends(get_db)):
    """Abre el probador para una prenda y color, devolviendo el recurso listo."""
    experiencia = IniciarExperiencia(db).execute(data.product_id, user, data.color_id)
    return ApiResponse(message="Vestidor virtual listo.", data=experiencia)


@router.get("/admin/products/{product_id}/assets", response_model=ApiResponse[list[RecursoTryOnResponse]])
def list_assets(product_id: uuid.UUID, user: CatalogReader, db: Session = Depends(get_db)):
    """Recursos preparados de una prenda, uno por color."""
    recursos = (
        db.query(TryOnAssetModel).filter(TryOnAssetModel.product_id == product_id).all()
    )
    return ApiResponse(message="Recursos obtenidos.", data=recursos)


@router.post("/admin/products/{product_id}/assets", response_model=ApiResponse[RecursoTryOnResponse])
def prepare_asset(
    product_id: uuid.UUID,
    data: PrepararRecursoRequest,
    user: CatalogWriter,
    db: Session = Depends(get_db),
):
    """Analiza la foto del producto y arma el recurso del probador."""
    recurso = PrepararPrenda(db).execute(product_id, data.color_id, user)
    return ApiResponse(message="Recurso preparado.", data=recurso)


@router.patch("/admin/assets/{asset_id}", response_model=ApiResponse[RecursoTryOnResponse])
def adjust_asset(
    asset_id: uuid.UUID,
    data: AjustarRecursoRequest,
    user: CatalogWriter,
    db: Session = Depends(get_db),
):
    """Corrección manual de lo que propuso el análisis automático.

    El ajuste a mano se conserva como respaldo: si el análisis se equivoca en la
    región del cuerpo o en los anclajes, el administrador los corrige sin tener
    que preparar la prenda de nuevo.
    """
    recurso = db.get(TryOnAssetModel, asset_id)
    if not recurso:
        raise NotFoundError("Recurso de probador no encontrado.")
    if not data.region_valida():
        raise ValidationError("Región corporal no válida.")

    cambios = data.model_dump(exclude_none=True)
    for campo, valor in cambios.items():
        setattr(recurso, campo, valor)
    if {"body_region", "anchor_points", "garment_type"} & cambios.keys():
        # Queda constancia de que la configuración final la fijó una persona.
        recurso.ai_status = ESTADO_MANUAL
    db.flush()
    RecordAuditEvent(db).execute(
        action="vestidor.asset_adjusted",
        entity_type="tryon_asset",
        entity_id=str(recurso.id),
        description="Recurso de probador ajustado manualmente.",
        actor_user_id=user.id,
        metadata={"fields": sorted(cambios.keys())},
    )
    db.commit()
    db.refresh(recurso)
    return ApiResponse(message="Recurso actualizado.", data=recurso)
