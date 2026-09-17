from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.shared.context.audit_context import get_audit_actor
from src.shared.exceptions.domain_exception import ConflictError, ValidationError
from src.usuarios_catalogo.infrastructure.models.catalog import ProductVariantModel
from src.ventas_pagos.infrastructure.models import StockModel, StockMovementModel


class StockService:
    """All callers share lock order: variant, then branch stock. Caller commits.

    Multi-item operations must call this service in ascending variant UUID order.
    Locking the variant also serializes creation of a missing stock row.
    """

    def __init__(self, db: Session):
        self.db = db

    def locked_stock(self, variant_id, branch_id):
        self.db.execute(select(ProductVariantModel.id).where(
            ProductVariantModel.id == variant_id).with_for_update())
        return self.db.scalar(select(StockModel).where(
            StockModel.variant_id == variant_id, StockModel.branch_id == branch_id
        ).with_for_update().execution_options(populate_existing=True))

    def change(self, variant_id, branch_id, delta, kind, reason, reference=None, actor_id=None):
        if isinstance(delta, bool) or not isinstance(delta, int):
            raise ValidationError("La cantidad debe ser un número entero.")
        row = self.locked_stock(variant_id, branch_id)
        previous = row.quantity if row else 0
        quantity = previous + delta
        if quantity < 0:
            raise ConflictError("Stock insuficiente. Actualizá las existencias antes de continuar.")
        if quantity > 1000000:
            raise ValidationError("Las existencias no pueden superar 1.000.000 de unidades.")
        if row is None:
            row = StockModel(variant_id=variant_id, branch_id=branch_id, quantity=quantity)
            self.db.add(row)
        else:
            row.quantity = quantity
        if delta:
            actor_id = actor_id or get_audit_actor()
            actor = self.db.get(UserModel, actor_id) if actor_id else None
            self.db.add(StockMovementModel(
                variant_id=variant_id, branch_id=branch_id, delta=delta,
                quantity_before=previous, quantity_after=quantity, kind=kind,
                reason=reason, reference=reference, actor_id=actor_id,
                actor_email=actor.email if actor else None,
            ))
        self.db.flush()
        return row

    def adjust(self, variant_id, branch_id, quantity, reason, actor_id=None):
        row = self.locked_stock(variant_id, branch_id)
        return self.change(variant_id, branch_id, quantity - (row.quantity if row else 0),
                           "adjustment", reason, actor_id=actor_id)
