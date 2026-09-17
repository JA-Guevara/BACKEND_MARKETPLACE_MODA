"""Disponibilidad de tallas concretas en una sucursal.

Hacer una reserva sirve para probarse una talla puntual: si esa talla no está
en la sucursal elegida, el cliente viaja al local para nada. Este caso de uso
responde, por cada variante pedida, si la sucursal la tiene, cuántas unidades y
si alcanza para la cantidad que el cliente quiere probarse.
"""
from uuid import UUID

from sqlalchemy.orm import Session

from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.shared.exceptions.domain_exception import ValidationError
from src.usuarios_catalogo.infrastructure.models.catalog import ProductVariantModel
from src.ventas_pagos.infrastructure.models import StockModel


class ConsultarDisponibilidad:
    def __init__(self, db: Session) -> None:
        self.db = db

    def execute(
        self,
        branch_id: UUID,
        variant_ids: list[UUID],
        quantities: list[int] | None = None,
    ) -> list[dict]:
        """Devuelve, en el mismo orden que ``variant_ids``, la disponibilidad de
        cada talla. ``quantities`` (opcional, una por variante pedida) permite
        distinguir "no tiene" de "no alcanza": la variante queda disponible solo
        si el stock cubre la cantidad solicitada."""
        branch = self.db.get(BranchModel, branch_id)
        if not branch or not branch.is_active or branch.deleted_at:
            raise ValidationError("Sucursal no disponible.")
        if not variant_ids:
            return []
        pedidos = [1] * len(variant_ids) if quantities is None else list(quantities)
        if len(pedidos) != len(variant_ids):
            raise ValidationError(
                "La cantidad solicitada no coincide con la lista de prendas."
            )

        if len(variant_ids) > 20 or any(q < 1 or q > 10 for q in pedidos):
            raise ValidationError("Consultá hasta 20 variantes con cantidades entre 1 y 10.")

        existencias = {
            fila.variant_id: fila.quantity
            for fila in self.db.query(StockModel)
            .filter(StockModel.branch_id == branch_id, StockModel.variant_id.in_(variant_ids))
            .all()
        }
        variantes = {
            variante.id: variante
            for variante in self.db.query(ProductVariantModel)
            .filter(ProductVariantModel.id.in_(variant_ids))
            .all()
        }

        resultado = []
        for variant_id, pedido in zip(variant_ids, pedidos):
            variante = variantes.get(variant_id)
            cantidad = existencias.get(variant_id, 0)
            publicada = bool(
                variante
                and variante.is_active
                and variante.product.is_active
                and not variante.product.deleted_at
            )
            suficiente = publicada and cantidad >= pedido
            if not publicada:
                reason = "La prenda ya no está publicada."
            elif cantidad == 0:
                reason = "Sin unidades en esta sucursal."
            elif cantidad < pedido:
                reason = f"Solo hay {cantidad} unidad(es) y pediste {pedido}."
            else:
                reason = None
            resultado.append(
                {
                    "variant_id": str(variant_id),
                    "available": bool(suficiente),
                    "quantity": cantidad if publicada else 0,
                    "requested": pedido,
                    "size": variante.size.name if variante else None,
                    "color": variante.color.name if variante else None,
                    "product": variante.product.name if variante else None,
                    "reason": reason,
                }
            )
        return resultado
