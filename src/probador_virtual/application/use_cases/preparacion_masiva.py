"""Reproceso masivo de recursos del probador (Fase 1 del plan de evolución).

No hay colas en el proyecto: la preparación es síncrona y esta operación la
corre el administrador cuando quiere reponer el catálogo. Se limita el lote y
se devuelve un resumen para no prometer un worker que todavía no existe.
"""
import uuid

from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.probador_virtual.application.use_cases.preparar_prenda import PrepararPrenda
from src.probador_virtual.infrastructure.persistence.models.recurso_tryon import (
    ESTADO_LISTO,
    ESTADO_MANUAL,
    ESTADO_REVISION,
    TryOnAssetModel,
)
from src.usuarios_catalogo.infrastructure.models.catalog import ColorModel, ProductModel

# Lote máximo por petición: con tiempos de descarga de la foto de fondo, pasar
# de esto haría expirar el request del administrador.
MAXIMO_LOTE = 60


class PreparacionMasiva:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._preparador = PrepararPrenda(db)

    def execute(
        self,
        product_ids: list[uuid.UUID] | None,
        only_pending: bool,
        actor: UserModel,
    ) -> dict:
        consulta = self.db.query(ProductModel).filter(
            ProductModel.deleted_at.is_(None), ProductModel.is_active.is_(True)
        )
        if product_ids:
            consulta = consulta.filter(ProductModel.id.in_(product_ids))
        productos = consulta.limit(MAXIMO_LOTE).all()
        if product_ids and len(product_ids) > MAXIMO_LOTE:
            productos = productos[:MAXIMO_LOTE]

        resumen = {
            "processed": 0,
            "ready": 0,
            "review": 0,
            "failed": 0,
            "errors": 0,
            "details": [],
        }
        for producto in productos:
            colores = self._colores_de(producto)
            for color in colores:
                if only_pending and self._ya_listo(producto.id, color.id):
                    continue
                try:
                    recurso = self._preparador.execute(producto.id, color.id, actor)
                    resumen[recurso.ai_status if recurso.ai_status in ("ready", "review", "failed") else "errors"] += 1
                    resumen["processed"] += 1
                    if len(resumen["details"]) < 30:
                        resumen["details"].append(
                            {
                                "product_id": str(producto.id),
                                "color_id": str(color.id),
                                "status": recurso.ai_status,
                                "quality_score": recurso.quality_score,
                                "quality_reason": recurso.quality_reason,
                            }
                        )
                except Exception as error:  # noqa: BLE001 - un producto no debe tumbar el lote
                    resumen["errors"] += 1
                    if len(resumen["details"]) < 30:
                        resumen["details"].append(
                            {
                                "product_id": str(producto.id),
                                "color_id": str(color.id),
                                "status": "error",
                                "error": str(error)[:200],
                            }
                        )
        return resumen

    def _colores_de(self, producto: ProductModel) -> list[ColorModel]:
        """Los colores que el producto vende de verdad (variantes activas), sin
        duplicados. Preparar un color que no existe en la prenda no tiene sentido."""
        vistos: set[uuid.UUID] = set()
        colores: list[ColorModel] = []
        for variante in producto.variants:
            if not variante.is_active or not variante.color_id or variante.color_id in vistos:
                continue
            vistos.add(variante.color_id)
            color = self.db.get(ColorModel, variante.color_id)
            if color:
                colores.append(color)
        return colores

    def _ya_listo(self, product_id: uuid.UUID, color_id: uuid.UUID) -> bool:
        existente = (
            self.db.query(TryOnAssetModel)
            .filter(
                TryOnAssetModel.product_id == product_id,
                TryOnAssetModel.color_id == color_id,
            )
            .first()
        )
        return bool(existente and existente.ai_status in (ESTADO_LISTO, ESTADO_MANUAL))