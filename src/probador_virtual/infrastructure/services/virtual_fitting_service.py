import uuid

from sqlalchemy.orm import Session

from src.probador_virtual.domain.entities.experiencia_virtual import ExperienciaVirtual
from src.probador_virtual.domain.exceptions import SinRecursoARError
from src.usuarios_catalogo.infrastructure.models.catalog import ProductModel


class VirtualFittingService:
    """Resuelve qué recurso AR corresponde a un producto. La composición visual
    (cámara + overlay) ocurre en el navegador; el backend solo valida y sirve
    la referencia del asset, y deja trazabilidad en la bitacora."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def resolve_asset(self, product_id: uuid.UUID) -> ExperienciaVirtual:
        product = self.db.get(ProductModel, product_id)
        if not product or not product.is_active or product.deleted_at:
            raise SinRecursoARError("Prenda no disponible.")
        asset = next(
            (a for a in product.ar_assets if a.is_active and a.asset_type == "image_overlay"),
            None,
        )
        if asset is None:
            raise SinRecursoARError("Esta prenda todavia no tiene un recurso de vestidor virtual cargado.")
        return ExperienciaVirtual(product_id=product.id, asset_type=asset.asset_type, asset_url=asset.asset_url)
