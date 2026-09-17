import uuid

from sqlalchemy.orm import Session

from src.probador_virtual.domain.entities.experiencia_virtual import ExperienciaVirtual
from src.probador_virtual.domain.exceptions import SinRecursoARError
from src.probador_virtual.infrastructure.persistence.models.recurso_tryon import TryOnAssetModel
from src.usuarios_catalogo.infrastructure.models.catalog import ProductModel


class VirtualFittingService:
    """Resuelve qué recurso corresponde a una prenda y color.

    Prefiere el recurso preparado (fondo recortado, región corporal y anclajes).
    Si no existe, cae al recurso AR cargado a mano, que solo permite el modo
    manual antiguo. La composición visual ocurre en el dispositivo; el backend
    valida, entrega la referencia y deja traza en la bitácora.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def _producto(self, product_id: uuid.UUID) -> ProductModel:
        producto = self.db.get(ProductModel, product_id)
        if not producto or not producto.is_active or producto.deleted_at:
            raise SinRecursoARError("Prenda no disponible.")
        return producto

    def resolve_asset(
        self, product_id: uuid.UUID, color_id: uuid.UUID | None = None
    ) -> ExperienciaVirtual:
        producto = self._producto(product_id)

        consulta = self.db.query(TryOnAssetModel).filter(TryOnAssetModel.product_id == product_id)
        if color_id:
            consulta = consulta.filter(TryOnAssetModel.color_id == color_id)
        recurso = next((r for r in consulta.all() if r.usable), None)
        if recurso:
            return ExperienciaVirtual(
                product_id=producto.id,
                color_id=recurso.color_id,
                mode=recurso.mode,
                asset_type="prepared_2_5d" if recurso.mode == "2.5d" else "model_3d",
                asset_url=recurso.transparent_url or recurso.model_3d_url or "",
                mask_url=recurso.mask_url,
                model_3d_url=recurso.model_3d_url,
                garment_type=recurso.garment_type,
                body_region=recurso.body_region,
                anchor_points=recurso.anchor_points,
            )

        if color_id:
            # Se pidió un color puntual y no tiene recurso propio: avisar en vez
            # de mostrar el de otro color.
            raise SinRecursoARError(
                "El probador virtual todavía no está preparado para este color."
            )

        legado = next(
            (a for a in producto.ar_assets if a.is_active and a.asset_type == "image_overlay"),
            None,
        )
        if legado is None:
            raise SinRecursoARError(
                "Esta prenda todavia no tiene un recurso de vestidor virtual preparado."
            )
        return ExperienciaVirtual(
            product_id=producto.id, asset_type=legado.asset_type, asset_url=legado.asset_url
        )
