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
from src.probador_virtual.application.use_cases.preparacion_masiva import PreparacionMasiva
from src.probador_virtual.application.use_cases.preparar_prenda import PrepararPrenda
from src.probador_virtual.infrastructure.http.schemas import (
    AjustarRecursoRequest,
    ExperienciaVirtualResponse,
    IniciarExperienciaRequest,
    PreparacionMasivaRequest,
    PreparacionMasivaResult,
    PrepararRecursoRequest,
    RecursoTryOnResponse,
    RevisarRecursoRequest,
)
from src.probador_virtual.infrastructure.persistence.models.recurso_tryon import (
    ESTADO_FALLIDO,
    ESTADO_LISTO,
    ESTADO_MANUAL,
    ESTADO_REVISION,
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


@router.get("/admin/assets", response_model=ApiResponse[list[RecursoTryOnResponse]])
def list_assets_review(
    user: CatalogReader,
    db: Session = Depends(get_db),
    status: str | None = None,
    product_id: uuid.UUID | None = None,
):
    """Lista de recursos del probador, con filtro por estado (por ejemplo
    `status=review` para la cola de recursos que esperan aprobación)."""
    recursos = db.query(TryOnAssetModel)
    if status:
        recursos = recursos.filter(TryOnAssetModel.ai_status == status)
    if product_id:
        recursos = recursos.filter(TryOnAssetModel.product_id == product_id)
    return ApiResponse(message="Recursos obtenidos.", data=recursos.all())


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


@router.post("/admin/assets/{asset_id}/retry", response_model=ApiResponse[RecursoTryOnResponse])
def retry_asset(
    asset_id: uuid.UUID,
    user: CatalogWriter,
    db: Session = Depends(get_db),
):
    """Vuelve a analizar la foto: la corrección de la imagen de la prenda o un
    fallo transitorio quedan resueltos con un intento nuevo, sin borrar nada."""
    recurso = db.get(TryOnAssetModel, asset_id)
    if not recurso:
        raise NotFoundError("Recurso de probador no encontrado.")
    recordado = PrepararPrenda(db).execute(recurso.product_id, recurso.color_id, user)
    return ApiResponse(message="Recurso reprocesado.", data=recordado)


@router.post(
    "/admin/assets/{asset_id}/review", response_model=ApiResponse[RecursoTryOnResponse]
)
def review_asset(
    asset_id: uuid.UUID,
    data: RevisarRecursoRequest,
    user: CatalogWriter,
    db: Session = Depends(get_db),
):
    """Aprueba o descarta un recurso que el análisis dejó en revisión. Hasta que
    alguien lo confirma no se publica: el probador cae al dibujo."""
    recurso = db.get(TryOnAssetModel, asset_id)
    if not recurso:
        raise NotFoundError("Recurso de probador no encontrado.")
    if recurso.ai_status not in (ESTADO_REVISION, ESTADO_LISTO, ESTADO_FALLIDO):
        raise ValidationError("El recurso no está esperando revisión.")

    if data.approve:
        if not recurso.transparent_url and not recurso.model_3d_url:
            raise ValidationError(
                "No se puede aprobar un recurso sin recorte: corregí la foto o el recurso a mano."
            )
        recurso.ai_status = ESTADO_LISTO
    else:
        recurso.ai_status = ESTADO_FALLIDO
        recurso.ai_error = data.note or (
            "Rechazado en revisión: la silueta no es confiable para el probador."
        )
    recurso.quality_reason = (data.note or recurso.quality_reason or "revisado")[:120]
    recurso.reviewed_by = user.id
    db.flush()
    RecordAuditEvent(db).execute(
        action="vestidor.asset_reviewed",
        entity_type="tryon_asset",
        entity_id=str(recurso.id),
        description="Recurso de probador aprobado." if data.approve else "Recurso de probador rechazado.",
        actor_user_id=user.id,
        metadata={
            "approve": data.approve,
            "quality_score": recurso.quality_score,
            "quality_reason": recurso.quality_reason,
        },
    )
    db.commit()
    db.refresh(recurso)
    return ApiResponse(
        message="Recurso aprobado y publicado." if data.approve else "Recurso descartado.",
        data=recurso,
    )


@router.post("/admin/bulk-prepare", response_model=ApiResponse[PreparacionMasivaResult])
def bulk_prepare(
    user: CatalogWriter,
    db: Session = Depends(get_db),
    data: PreparacionMasivaRequest | None = None,
):
    """Prepara en lote los recursos de los productos indicados (o todos). Con
    `only_pending` solo reprocesa los que no quedaron listos o manuales."""
    data = data or PreparacionMasivaRequest()
    resumen = PreparacionMasiva(db).execute(data.product_ids, data.only_pending, user)
    RecordAuditEvent(db).execute(
        action="vestidor.assets_bulk_prepared",
        entity_type="tryon_asset",
        entity_id="bulk",
        description=f"Preparación masiva: {resumen['processed']} recursos.",
        actor_user_id=user.id,
        metadata={
            "processed": resumen["processed"],
            "ready": resumen["ready"],
            "review": resumen["review"],
            "failed": resumen["failed"],
            "errors": resumen["errors"],
        },
    )
    db.commit()
    return ApiResponse(message="Preparación masiva terminada.", data=resumen)


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
        recurso.reviewed_by = user.id
        recurso.quality_reason = (recurso.quality_reason or "") + "; ajuste_manual"
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
