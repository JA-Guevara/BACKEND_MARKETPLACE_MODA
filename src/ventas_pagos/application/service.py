import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session
from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.config.settings import settings
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError, ValidationError
from src.usuarios_catalogo.infrastructure.models.catalog import ProductVariantModel
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.ventas_pagos.infrastructure.models import StockModel, CartItemModel, OrderModel, WebhookEventModel
from src.ventas_pagos.infrastructure import gateways
from src.ventas_pagos.domain.states import TRANSITIONS


class CommerceService:
    def __init__(self, db: Session):
        self.db = db

    def branch(self, branch_id):
        branch = self.db.get(BranchModel, branch_id)
        if not branch or not branch.is_active or branch.deleted_at:
            raise ValidationError("Sucursal no disponible.")
        return branch

    def variant(self, variant_id):
        variant = self.db.get(ProductVariantModel, variant_id)
        if not variant or not variant.is_active or not variant.product.is_active or variant.product.deleted_at:
            raise NotFoundError("La variante no esta disponible.")
        return variant

    def snapshot(self, variant, quantity, branch_id):
        stock = self.db.scalar(select(StockModel).where(StockModel.variant_id == variant.id, StockModel.branch_id == branch_id)) if branch_id else None
        price = variant.price_override if variant.price_override is not None else variant.product.base_price
        return {"variant_id": str(variant.id), "product_id": str(variant.product_id), "name": variant.product.name,
            "sku": variant.sku, "size": variant.size.name, "color": variant.color.name,
            "image_url": variant.product.images[0].url if variant.product.images else None,
            "unit_price": str(price), "quantity": quantity, "available": stock.quantity if stock else 0,
            "line_total": str(price * quantity)}

    def cart(self, user, branch_id=None):
        rows = self.db.scalars(select(CartItemModel).where(CartItemModel.user_id == user.id)).all()
        items = [self.snapshot(self.variant(row.variant_id), row.quantity, branch_id) for row in rows]
        return {"items": items, "total": str(sum((Decimal(item["line_total"]) for item in items), Decimal(0))), "currency": settings.commerce_currency}

    def set_cart(self, user, variant_id, quantity):
        self.variant(variant_id)
        self.db.execute(select(UserModel.id).where(UserModel.id == user.id).with_for_update())
        row = self.db.scalar(select(CartItemModel).where(CartItemModel.user_id == user.id, CartItemModel.variant_id == variant_id))
        if row:
            row.quantity = quantity
        else:
            self.db.add(CartItemModel(user_id=user.id, variant_id=variant_id, quantity=quantity))
        self.db.commit()

    def order(self, order_id, user=None):
        query = select(OrderModel).where(OrderModel.id == order_id)
        if user is not None:
            query = query.where(OrderModel.user_id == user.id)
        order = self.db.scalar(query.with_for_update())
        if not order:
            raise NotFoundError("Pedido no encontrado.")
        return order

    def create_order(self, user, data):
        self.branch(data.branch_id)
        self.db.execute(select(UserModel.id).where(UserModel.id == user.id).with_for_update())
        cart = self.cart(user, data.branch_id)
        if not cart["items"]:
            raise ValidationError("El carrito esta vacio.")
        try:
            for item in sorted(cart["items"], key=lambda x: x["variant_id"]):
                result = self.db.execute(update(StockModel).where(StockModel.variant_id == uuid.UUID(item["variant_id"]),
                    StockModel.branch_id == data.branch_id, StockModel.quantity >= item["quantity"])
                    .values(quantity=StockModel.quantity - item["quantity"]))
                if result.rowcount != 1:
                    raise ConflictError("Stock insuficiente para " + item["name"])
            order = OrderModel(number="FS-" + uuid.uuid4().hex[:12].upper(), user_id=user.id,
                branch_id=data.branch_id, customer_email=user.email, payment_method=data.payment_method,
                total=Decimal(cart["total"]), currency=cart["currency"], address=data.address.model_dump(), items=cart["items"],
                tracking=[{"status": "pending_payment", "note": "Pedido creado; existencias reservadas.", "date": datetime.now(timezone.utc).isoformat()}])
            self.db.add(order)
            self.db.execute(delete(CartItemModel).where(CartItemModel.user_id == user.id))
            self.db.commit()
            self.db.refresh(order)
            return order
        except Exception:
            self.db.rollback()
            raise

    def release(self, order, status):
        for item in order.items:
            self.db.execute(update(StockModel).where(StockModel.variant_id == uuid.UUID(item["variant_id"]), StockModel.branch_id == order.branch_id)
                .values(quantity=StockModel.quantity + item["quantity"]))
        order.status = status
        order.payment_status = "cancelled"
        self.track(order, "Existencias liberadas.")

    @staticmethod
    def track(order, note):
        order.tracking = [*order.tracking, {"status": order.status, "note": note, "date": datetime.now(timezone.utc).isoformat()}]

    def cancel(self, order):
        if order.status != "pending_payment":
            raise ConflictError("Solo se pueden cancelar pedidos pendientes de pago.")
        if order.stripe_session_id:
            gateways.stripe_request("POST", f"checkout/sessions/{order.stripe_session_id}/expire")
        self.release(order, "cancelled")
        self.db.commit()
        return order

    def checkout(self, order):
        if order.status != "pending_payment" or order.payment_method != "stripe":
            raise ConflictError("Pedido no disponible para pago con Stripe.")
        if not order.stripe_session_id:
            session = gateways.create_session(order)
            order.stripe_session_id, order.stripe_url = session["id"], session["url"]
            self.db.commit()
        return {"session_id": order.stripe_session_id, "url": order.stripe_url}

    def manual_payment(self, order, data):
        if order.status != "pending_payment" or order.payment_method != "manual":
            raise ConflictError("Solo se confirman pagos manuales pendientes.")
        order.payment_method, order.payment_reference = data.method, data.reference
        order.status, order.payment_status = "paid", "paid"
        self.track(order, "Pago presencial/transferencia confirmado por administracion.")
        self.db.commit()
        return order

    def tracking(self, order, data):
        if data.status not in TRANSITIONS.get(order.status, set()):
            raise ConflictError("Transicion de seguimiento no permitida.")
        if data.status == "shipped" and not (data.carrier and data.tracking_number):
            raise ValidationError("Indique transportista y numero de seguimiento.")
        order.status = data.status
        order.carrier = data.carrier or order.carrier
        order.tracking_number = data.tracking_number or order.tracking_number
        self.track(order, data.note or "Estado actualizado por administracion.")
        self.db.commit()
        return order

    def webhook(self, event):
        supported = {"checkout.session.completed", "checkout.session.expired", "checkout.session.async_payment_succeeded"}
        if event.get("type") not in supported:
            return {"received": True}
        session = event["data"]["object"]
        order = self.db.scalar(select(OrderModel).where(OrderModel.stripe_session_id == session["id"]).with_for_update())
        if not order:
            raise ConflictError("Sesion pendiente de asociacion; Stripe debe reintentar.")
        if self.db.scalar(select(WebhookEventModel.id).where(WebhookEventModel.event_id == event["id"])):
            return {"received": True, "duplicate": True}
        if order.status == "pending_payment":
            if event["type"] == "checkout.session.expired":
                self.release(order, "expired")
            elif session.get("payment_status") == "paid":
                if session.get("currency") != order.currency or session.get("amount_total") != int(order.total * 100) or session.get("client_reference_id") != str(order.id):
                    raise ConflictError("La confirmacion no coincide con el pedido.")
                order.status, order.payment_status = "paid", "paid"
                order.payment_reference = session.get("payment_intent")
                self.track(order, "Pago de prueba confirmado por webhook firmado de Stripe.")
        self.db.add(WebhookEventModel(event_id=event["id"]))
        self.db.commit()
        return {"received": True}
