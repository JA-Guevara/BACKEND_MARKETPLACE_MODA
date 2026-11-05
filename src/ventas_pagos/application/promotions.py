"""Evaluación centralizada de cupones y promociones.

El navegador solo muestra el resultado. Toda condición, vigencia y límite se
valida aquí al cotizar y se vuelve a validar al crear el pedido.
"""
import uuid
from typing import Any
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.shared.exceptions.domain_exception import ConflictError, NotFoundError, ValidationError
from src.usuarios_catalogo.infrastructure.models.catalog import ProductModel, ProductVariantModel
from src.ventas_pagos.domain.promociones import estado as calc_estado, precio_final, validar as validar_reglas
from src.ventas_pagos.infrastructure.engagement_models import (
    PromotionModel,
    PromotionTargetModel,
    PromotionUseModel,
)
from src.ventas_pagos.infrastructure.models import OrderModel
from src.ventas_pagos.web.offer_schemas import (
    OfferIn,
    OfferOut,
    OfferPreview,
    OfferPreviewItem,
    OfferTargetIn,
    OfferTargetOut,
    OfferUpdate,
)

CENT = Decimal("0.01")


class PromotionService:
    def __init__(self, db: Session, tenant_id: uuid.UUID | None = None):
        self.db = db
        self.tenant_id = tenant_id

    def listar(self, active: bool | None = None, is_coupon: bool | None = None) -> list[OfferOut]:
        query = select(PromotionModel).order_by(PromotionModel.created_at.desc())
        if self.tenant_id is not None:
            query = query.where(PromotionModel.tenant_id == self.tenant_id)
        if active is not None:
            query = query.where(PromotionModel.is_active.is_(active))
        if is_coupon is not None:
            if is_coupon:
                query = query.where(PromotionModel.code.is_not(None))
            else:
                query = query.where(PromotionModel.code.is_(None))

        rows = list(self.db.scalars(query).all())
        ahora = datetime.now(timezone.utc)
        return [self._to_out(r, ahora) for r in rows]

    def obtener(self, id: uuid.UUID) -> OfferOut:
        p = self.db.get(PromotionModel, id)
        if not p or (self.tenant_id and p.tenant_id != self.tenant_id):
            raise NotFoundError("La oferta o promoción no existe.")
        return self._to_out(p, datetime.now(timezone.utc))

    def previsualizar(self, data: OfferIn) -> OfferPreview:
        variants = self._resolve_target_variants(data.target)
        regulares: list[Decimal] = []
        items: list[OfferPreviewItem] = []

        for v in variants[:25]:  # Muestra hasta 25 prendas
            reg = Decimal(str(v.price_override if v.price_override is not None else v.product.base_price))
            regulares.append(reg)
            fin = precio_final(reg, data.discount_type, data.discount_value)
            pname = v.product.name
            size_name = getattr(v.size, "name", "")
            color_name = getattr(v.color, "name", "")
            variant_desc = f"{size_name} / {color_name}".strip(" /")
            items.append(OfferPreviewItem(
                product_name=pname,
                variant=variant_desc or v.sku,
                regular=reg.quantize(CENT),
                final=fin,
            ))

        # Para validación se toman todos los precios regulares
        all_regulares = [
            Decimal(str(v.price_override if v.price_override is not None else v.product.base_price))
            for v in variants
        ]
        errores = validar_reglas(
            tipo=data.discount_type,
            valor=data.discount_value,
            inicio=data.starts_at,
            fin=data.ends_at,
            regulares=all_regulares,
        )

        return OfferPreview(items=items, errors=errores)

    def crear(self, data: OfferIn, actor: Any) -> OfferOut:
        # 1. Validar unicidad de cupón en la empresa
        if data.code:
            code_upper = data.code.strip().upper()
            existing = self.db.scalar(
                select(PromotionModel).where(
                    PromotionModel.tenant_id == self.tenant_id,
                    func.upper(PromotionModel.code) == code_upper,
                )
            )
            if existing:
                raise ConflictError("Ya existe una promoción o cupón con este código en la empresa.")
        else:
            code_upper = None

        # 2. Validar precios regulares
        variants = self._resolve_target_variants(data.target)
        all_regulares = [
            Decimal(str(v.price_override if v.price_override is not None else v.product.base_price))
            for v in variants
        ]
        errores = validar_reglas(
            tipo=data.discount_type,
            valor=data.discount_value,
            inicio=data.starts_at,
            fin=data.ends_at,
            regulares=all_regulares,
        )
        if errores:
            raise ValidationError("La oferta no cumple las reglas comerciales.", details={"errors": errores})

        promo = PromotionModel(
            tenant_id=self.tenant_id or uuid.UUID("30000000-0000-0000-0000-000000000001"),
            name=data.name,
            code=code_upper,
            description=data.description,
            discount_type=data.discount_type,
            discount_value=data.discount_value,
            minimum_order=data.minimum_order,
            starts_at=data.starts_at,
            ends_at=data.ends_at,
            max_uses=data.max_uses,
            per_user_limit=data.per_user_limit,
            applies_online=data.applies_online,
            applies_pos=data.applies_pos,
            applies_offline=data.applies_offline,
            is_active=True,
            created_by=getattr(actor, "id", None),
        )
        self.db.add(promo)
        self.db.flush()

        # Guardar targets
        for tid in data.target.ids:
            self.db.add(PromotionTargetModel(
                promotion_id=promo.id,
                target_type=data.target.type,
                target_id=tid,
            ))
        if data.target.type == "ALL":
            self.db.add(PromotionTargetModel(
                promotion_id=promo.id,
                target_type="ALL",
                target_id=promo.id,
            ))

        self.db.commit()
        self.db.refresh(promo)
        return self._to_out(promo, datetime.now(timezone.utc))

    def actualizar(self, id: uuid.UUID, data: OfferUpdate, actor: Any) -> OfferOut:
        promo = self.db.get(PromotionModel, id)
        if not promo or (self.tenant_id and promo.tenant_id != self.tenant_id):
            raise NotFoundError("La oferta no existe.")

        if data.name is not None:
            promo.name = data.name
        if data.description is not None:
            promo.description = data.description
        if data.discount_value is not None:
            promo.discount_value = data.discount_value
        if data.starts_at is not None:
            promo.starts_at = data.starts_at
        if data.ends_at is not None:
            promo.ends_at = data.ends_at
        if data.max_uses is not None:
            promo.max_uses = data.max_uses
        if data.per_user_limit is not None:
            promo.per_user_limit = data.per_user_limit
        if data.applies_online is not None:
            promo.applies_online = data.applies_online
        if data.applies_pos is not None:
            promo.applies_pos = data.applies_pos
        if data.applies_offline is not None:
            promo.applies_offline = data.applies_offline

        promo.updated_by = getattr(actor, "id", None)

        if data.target is not None:
            # Reemplazar targets
            for t in list(promo.targets):
                self.db.delete(t)
            self.db.flush()
            for tid in data.target.ids:
                self.db.add(PromotionTargetModel(
                    promotion_id=promo.id,
                    target_type=data.target.type,
                    target_id=tid,
                ))
            if data.target.type == "ALL":
                self.db.add(PromotionTargetModel(
                    promotion_id=promo.id,
                    target_type="ALL",
                    target_id=promo.id,
                ))

        self.db.commit()
        self.db.refresh(promo)
        return self._to_out(promo, datetime.now(timezone.utc))

    def activar(self, id: uuid.UUID, actor: Any) -> OfferOut:
        promo = self.db.get(PromotionModel, id)
        if not promo or (self.tenant_id and promo.tenant_id != self.tenant_id):
            raise NotFoundError("La oferta no existe.")
        promo.is_active = True
        promo.deactivated_at = None
        promo.updated_by = getattr(actor, "id", None)
        self.db.commit()
        self.db.refresh(promo)
        return self._to_out(promo, datetime.now(timezone.utc))

    def desactivar(self, id: uuid.UUID, actor: Any) -> OfferOut:
        promo = self.db.get(PromotionModel, id)
        if not promo or (self.tenant_id and promo.tenant_id != self.tenant_id):
            raise NotFoundError("La oferta no existe.")
        promo.is_active = False
        promo.deactivated_at = datetime.now(timezone.utc)
        promo.deactivated_by = getattr(actor, "id", None)
        promo.updated_by = getattr(actor, "id", None)
        self.db.commit()
        self.db.refresh(promo)
        return self._to_out(promo, datetime.now(timezone.utc))

    def _resolve_target_variants(self, target: OfferTargetIn) -> list[ProductVariantModel]:
        stmt = (
            select(ProductVariantModel)
            .join(ProductModel)
            .where(ProductVariantModel.is_active.is_(True), ProductModel.deleted_at.is_(None))
        )
        if self.tenant_id:
            stmt = stmt.where(ProductModel.tenant_id == self.tenant_id)

        if target.type == "VARIANT" and target.ids:
            stmt = stmt.where(ProductVariantModel.id.in_(target.ids))
        elif target.type == "PRODUCT" and target.ids:
            stmt = stmt.where(ProductModel.id.in_(target.ids))
        elif target.type == "CATEGORY" and target.ids:
            stmt = stmt.where(ProductModel.category_id.in_(target.ids))
        elif target.type == "SEASON" and target.ids:
            stmt = stmt.where(ProductModel.season_id.in_(target.ids))
        elif target.type == "COLLECTION" and target.ids:
            stmt = stmt.where(ProductModel.collection_id.in_(target.ids))

        return list(self.db.scalars(stmt).all())

    def _to_out(self, p: PromotionModel, ahora: datetime) -> OfferOut:
        st = calc_estado(p, ahora)
        target_type = "ALL"
        target_ids: list[uuid.UUID] = []
        if p.targets:
            target_type = p.targets[0].target_type
            target_ids = [t.target_id for t in p.targets if t.target_type != "ALL"]

        return OfferOut(
            id=p.id,
            name=p.name,
            code=p.code,
            description=p.description,
            discount_type=p.discount_type,
            discount_value=p.discount_value,
            minimum_order=p.minimum_order,
            target=OfferTargetOut(type=target_type, ids=target_ids),
            starts_at=p.starts_at,
            ends_at=p.ends_at,
            max_uses=p.max_uses,
            uses_count=p.uses_count,
            per_user_limit=p.per_user_limit,
            is_active=p.is_active,
            applies_online=p.applies_online,
            applies_pos=p.applies_pos,
            applies_offline=p.applies_offline,
            status=st,
            created_at=p.created_at,
            deactivated_at=p.deactivated_at,
        )

    def quote(self, user, items: list[dict], coupon_code: str | None = None, *, lock: bool = False) -> dict:
        subtotal = sum((Decimal(str(row["line_total"])) for row in items), Decimal(0))
        now = datetime.now(timezone.utc)
        query = select(PromotionModel).where(PromotionModel.is_active.is_(True))
        if self.tenant_id is not None:
            query = query.where(PromotionModel.tenant_id == self.tenant_id)
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
            if self.tenant_id and promotion.tenant_id != self.tenant_id:
                raise ConflictError("La promoción no pertenece a la empresa.")
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
            query = select(func.count(OrderModel.id)).where(
                OrderModel.user_id == user.id, OrderModel.payment_status == "paid"
            )
            if self.tenant_id:
                query = query.where(OrderModel.tenant_id == self.tenant_id)
            paid = self.db.scalar(query) or 0
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
