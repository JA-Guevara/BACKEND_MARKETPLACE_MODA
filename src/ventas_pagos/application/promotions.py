"""Evaluación centralizada de cupones y promociones.

El navegador solo muestra el resultado. Toda condición, vigencia y límite se
valida aquí al cotizar y se vuelve a validar al crear el pedido.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.shared.exceptions.domain_exception import ConflictError, ValidationError
from src.ventas_pagos.infrastructure.engagement_models import PromotionModel, PromotionUseModel
from src.ventas_pagos.infrastructure.models import OrderModel

CENT = Decimal("0.01")


class PromotionService:
    def __init__(self, db: Session):
        self.db = db

    def quote(self, user, items: list[dict], coupon_code: str | None = None, *, lock: bool = False) -> dict:
        subtotal = sum((Decimal(str(row["line_total"])) for row in items), Decimal(0))
        now = datetime.now(timezone.utc)
        query = select(PromotionModel).where(PromotionModel.is_active.is_(True))
        if lock:
            query = query.with_for_update()
        promos = list(self.db.scalars(query).all())
        automatic = [p for p in promos if not p.code]
        selected: list[PromotionModel] = []
        # Solo la mejor campaña automática: dos rebajas de temporada no se apilan.
        candidates = [p for p in automatic if self._eligible(p, user, items, subtotal, now)]
        if candidates:
            selected.append(max(candidates, key=lambda p: self._amount(p, self._scope_total(p, items))))
        code = (coupon_code or "").strip().upper()
        if code:
            promo = next((p for p in promos if p.code and p.code.upper() == code), None)
            if not promo:
                raise ValidationError("El cupón no existe.")
            if not self._eligible(promo, user, items, subtotal, now):
                raise ValidationError("El cupón no aplica a este carrito o ya no está vigente.")
            selected.append(promo)
        discounts = []
        remaining = subtotal
        for promotion in selected:
            eligible_total = min(self._scope_total(promotion, items), remaining)
            amount = self._amount(promotion, eligible_total)
            if promotion.discount_type == "free_shipping":
                # Aún no se cobra flete en FashionStore: la campaña se conserva
                # como beneficio visible sin inventar un descuento monetario.
                amount = Decimal(0)
            if amount <= 0 and promotion.discount_type != "free_shipping":
                continue
            remaining = max(Decimal(0), remaining - amount)
            discounts.append({
                "promotion_id": str(promotion.id), "name": promotion.name,
                "code": promotion.code, "type": promotion.discount_type,
                "amount": str(amount.quantize(CENT)),
                "message": "Envío gratis coordinado con la tienda." if promotion.discount_type == "free_shipping" else None,
            })
        discount_total = sum((Decimal(row["amount"]) for row in discounts), Decimal(0))
        return {
            "subtotal": str(subtotal.quantize(CENT)), "discount_total": str(discount_total.quantize(CENT)),
            "total": str(max(Decimal(0), subtotal - discount_total).quantize(CENT)),
            "discounts": discounts, "coupon_code": code or None,
        }

    def record_uses(self, user, order, quote: dict) -> None:
        for discount in quote["discounts"]:
            promotion = self.db.get(PromotionModel, discount["promotion_id"])
            if not promotion:
                raise ConflictError("Una promoción cambió mientras se confirmaba el pedido.")
            if promotion.max_uses is not None and promotion.uses_count >= promotion.max_uses:
                raise ConflictError("La promoción alcanzó su límite de usos.")
            if promotion.per_user_limit is not None:
                used = self.db.scalar(select(func.count(PromotionUseModel.id)).where(
                    PromotionUseModel.promotion_id == promotion.id, PromotionUseModel.user_id == user.id
                )) or 0
                if used >= promotion.per_user_limit:
                    raise ConflictError("Ya usaste esta promoción el máximo permitido.")
            promotion.uses_count += 1
            self.db.add(PromotionUseModel(
                promotion_id=promotion.id, user_id=user.id, order_id=order.id,
                amount=Decimal(discount["amount"]),
            ))

    def _eligible(self, p, user, items, subtotal, now) -> bool:
        if (p.starts_at and p.starts_at > now) or (p.ends_at and p.ends_at < now): return False
        if p.max_uses is not None and p.uses_count >= p.max_uses: return False
        if subtotal < p.minimum_order or self._scope_total(p, items) <= 0: return False
        if p.customer_scope == "frequent":
            paid = self.db.scalar(select(func.count(OrderModel.id)).where(
                OrderModel.user_id == user.id, OrderModel.payment_status == "paid"
            )) or 0
            if paid < max(1, p.minimum_paid_orders): return False
        return True

    @staticmethod
    def _scope_total(p, items) -> Decimal:
        matched = items
        if p.product_id:
            matched = [i for i in matched if str(i["product_id"]) == str(p.product_id)]
        elif p.category_id:
            matched = [i for i in matched if str(i.get("category_id")) == str(p.category_id)]
        return sum((Decimal(str(i["line_total"])) for i in matched), Decimal(0))

    @staticmethod
    def _amount(p, base: Decimal) -> Decimal:
        if p.discount_type == "percent":
            return min(base, (base * p.discount_value / Decimal(100)).quantize(CENT, ROUND_HALF_UP))
        if p.discount_type == "fixed": return min(base, p.discount_value.quantize(CENT, ROUND_HALF_UP))
        return Decimal(0)
