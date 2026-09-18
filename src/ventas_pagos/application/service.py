import uuid
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session
from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.config.settings import settings
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError, ValidationError
from src.usuarios_catalogo.infrastructure.models.catalog import ProductModel, ProductVariantModel
from src.inventario_sucursales.infrastructure.models.organization import BranchModel, CashPointModel
from src.ventas_pagos.infrastructure.models import StockModel, CartItemModel, OrderModel, WebhookEventModel
from src.ventas_pagos.infrastructure import gateways
from src.ventas_pagos.domain.states import TRANSITIONS
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.ventas_pagos.application.stock_service import StockService
from src.notificaciones.application.use_cases.send_notification import notificar_pedido


class CommerceService:
    def __init__(self, db: Session):
        self.db = db

    def audit(self, order, action, description):
        RecordAuditEvent(self.db).execute(action="commerce." + action, entity_type="order", entity_id=str(order.id), description=description, metadata={"number":order.number,"status":order.status,"payment_status":order.payment_status})

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
        items = []
        for row in rows:
            variant = self.db.get(ProductVariantModel, row.variant_id)
            if variant is None:
                continue
            item = self.snapshot(variant, row.quantity, branch_id)
            if not variant.is_active or not variant.product.is_active or variant.product.deleted_at:
                item["available"] = 0
            items.append(item)
        return {"items": items, "total": str(sum((Decimal(item["line_total"]) for item in items), Decimal(0))), "currency": settings.commerce_currency}

    def recommendations(self, user, limit: int = 8):
        """RF25/CU23: recomendador simple y determinista (sin depender de un
        servicio externo en vivo). Si el cliente tiene compras pagadas previas,
        prioriza las mismas categorias; si no, muestra destacados."""
        query = select(ProductModel).where(ProductModel.is_active.is_(True), ProductModel.deleted_at.is_(None))
        category_ids: list = []
        exclude_ids: set = set()
        if user is not None:
            paid_orders = self.db.scalars(select(OrderModel).where(OrderModel.user_id == user.id, OrderModel.payment_status == "paid")).all()
            product_ids = {uuid.UUID(item["product_id"]) for order in paid_orders for item in order.items}
            if product_ids:
                exclude_ids = product_ids
                category_ids = list(self.db.scalars(select(ProductModel.category_id).where(ProductModel.id.in_(product_ids)).distinct()))
        if category_ids:
            products = list(self.db.scalars(query.where(ProductModel.category_id.in_(category_ids), ProductModel.id.notin_(exclude_ids)).order_by(ProductModel.created_at.desc()).limit(limit)))
        else:
            products = list(self.db.scalars(query.where(ProductModel.is_featured.is_(True)).order_by(ProductModel.created_at.desc()).limit(limit)))
        if len(products) < limit:
            have = {p.id for p in products} | exclude_ids
            filler = self.db.scalars(query.where(ProductModel.id.notin_(have)).order_by(ProductModel.is_featured.desc(), ProductModel.created_at.desc()).limit(limit - len(products)))
            products = [*products, *filler]
        return [{
            "id": str(p.id), "slug": p.slug, "name": p.name, "base_price": str(p.base_price),
            "image_url": p.images[0].url if p.images else None, "category": p.category.name,
        } for p in products]

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
                self.variant(uuid.UUID(item["variant_id"]))
                StockService(self.db).change(uuid.UUID(item["variant_id"]), data.branch_id,
                    -item["quantity"], "web_order_hold", "Existencias reservadas para pedido web.",
                    reference="nuevo-pedido", actor_id=user.id)
            order = OrderModel(number="FS-" + uuid.uuid4().hex[:12].upper(), user_id=user.id,
                branch_id=data.branch_id, customer_email=user.email, payment_method=data.payment_method,
                total=Decimal(cart["total"]), currency=cart["currency"], address=data.address.model_dump(), items=cart["items"],
                tracking=[{"status": "pending_payment", "note": "Pedido creado; existencias reservadas.", "date": datetime.now(timezone.utc).isoformat()}])
            self.db.add(order)
            self.db.flush()
            self.audit(order, "order_created", "Pedido creado con reserva de existencias.")
            self.db.execute(delete(CartItemModel).where(CartItemModel.user_id == user.id))
            self.db.commit()
            self.db.refresh(order)
            # CU15: el cliente recibe el aviso recien cuando el pedido quedo
            # guardado; un fallo de correo no debe deshacer la compra. La
            # sucursal tambien, porque ya tiene prendas apartadas por preparar.
            notificar_pedido(self.db, order, avisar_sucursal=True)
            return order
        except Exception:
            self.db.rollback()
            raise

    def release(self, order, status):
        for item in sorted(order.items, key=lambda row: row["variant_id"]):
            StockService(self.db).change(uuid.UUID(item["variant_id"]), order.branch_id,
                item["quantity"], "web_order_release", "Existencias liberadas por pedido no cobrado.",
                reference=order.number)
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
        self.audit(order, "order_cancelled", "Pedido cancelado; existencias liberadas.")
        self.db.commit()
        notificar_pedido(self.db, order)
        return order

    def checkout(self, order):
        if order.payment_method == "stripe" and order.stripe_session_id:
            self.reconcile_payment(order)
        if order.payment_status == "paid":
            return {"status": order.status, "url": None}
        if order.status != "pending_payment" or order.payment_method != "stripe":
            raise ConflictError("Pedido no disponible para pago con Stripe.")
        if not order.stripe_session_id:
            session = gateways.create_session(order)
            order.stripe_session_id, order.stripe_url = session["id"], session["url"]
            self.db.commit()
        return {"session_id": order.stripe_session_id, "url": order.stripe_url}

    def confirm_stripe_payment(self, order, session, note, confirmed_at=None):
        if (session.get("id") != order.stripe_session_id
                or session.get("currency", "").lower() != order.currency.lower()
                or session.get("amount_total") != int(order.total * 100)
                or session.get("client_reference_id") != str(order.id)):
            raise ConflictError("La confirmacion no coincide con el pedido.")
        if order.payment_status == "paid":
            return False
        if order.status != "pending_payment":
            raise ConflictError("El pedido ya no admite confirmaciones de pago; requiere revision.")
        intent = session.get("payment_intent")
        reference = intent.get("id") if isinstance(intent, dict) else intent
        if not reference:
            raise ConflictError("Stripe no devolvio la referencia del pago.")
        charge = intent.get("latest_charge") if isinstance(intent, dict) else None
        paid_timestamp = charge.get("created") if isinstance(charge, dict) else confirmed_at
        order.status, order.payment_status = "paid", "paid"
        order.paid_at = datetime.fromtimestamp(paid_timestamp, timezone.utc) if paid_timestamp else datetime.now(timezone.utc)
        order.payment_reference = reference
        self.track(order, note)
        return True

    def reconcile_payment(self, order):
        """Recupera confirmaciones atrasadas consultando Stripe desde el servidor.

        El llamador obtiene order() con bloqueo y control de propietario/permisos.
        Comparte transicion con webhook: no descuenta stock ni acredita dos veces.
        """
        if order.payment_method != "stripe" or order.payment_status == "paid" or order.status != "pending_payment":
            return order
        if not order.stripe_session_id:
            return order
        session = gateways.retrieve_session(order.stripe_session_id)
        if (session.get("id") != order.stripe_session_id or session.get("livemode") is not False
                or session.get("mode") != "payment"):
            raise ConflictError("La sesion consultada no corresponde a un pago de prueba valido.")
        if session.get("status") == "complete" and session.get("payment_status") == "paid":
            self.confirm_stripe_payment(order, session, "Pago confirmado mediante consulta segura a Stripe.")
            self.audit(order, "payment_reconciled", "Pago confirmado consultando Stripe desde el backend.")
            self.db.commit()
            notificar_pedido(self.db, order)
        elif session.get("status") == "expired":
            self.release(order, "expired")
            self.audit(order, "payment_expired", "Sesion de Stripe expirada; existencias liberadas.")
            self.db.commit()
            notificar_pedido(self.db, order)
        return order

    def manual_payment(self, order, data):
        if order.status != "pending_payment" or order.payment_method != "manual":
            raise ConflictError("Solo se confirman pagos manuales pendientes.")
        order.payment_method, order.payment_reference = data.method, data.reference
        order.status, order.payment_status = "paid", "paid"
        order.paid_at = datetime.now(timezone.utc)
        self.track(order, "Pago presencial/transferencia confirmado por administracion.")
        self.audit(order, "payment_confirmed", "Pago manual confirmado por administracion.")
        self.db.commit()
        notificar_pedido(self.db, order)
        return order

    def pos_sale(self, actor, data):
        """Registers an already received in-person payment atomically.

        The frontend supplies only identities and quantities. Product prices,
        branch availability and totals always come from the server.
        """
        fingerprint_data = {
            "branch_id": str(data.branch_id), "cash_point_id": str(data.cash_point_id),
            "customer_name": data.customer_name, "customer_email": data.customer_email or "",
            "payment_method": data.payment_method, "payment_reference": data.payment_reference,
            "items": sorted([{"variant_id": str(row.variant_id), "quantity": row.quantity} for row in data.items], key=lambda row: row["variant_id"]),
        }
        fingerprint = hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        try:
            # This lock serializes retries that target the same physical cash point.
            cash_point = self.db.scalar(select(CashPointModel).where(CashPointModel.id == data.cash_point_id).with_for_update())
            if not cash_point or cash_point.deleted_at or not cash_point.is_active:
                raise ValidationError("El punto de caja no está disponible.")
            if cash_point.branch_id != data.branch_id:
                raise ValidationError("El punto de caja no pertenece a la sucursal seleccionada.")
            self.branch(data.branch_id)
            replay = self.db.scalar(select(OrderModel).where(OrderModel.client_request_id == data.client_request_id).with_for_update())
            if replay:
                if replay.cashier_user_id != actor.id or replay.request_fingerprint != fingerprint:
                    raise ConflictError("La clave de esta venta ya fue utilizada con otros datos.")
                return replay, True

            known_user = None
            if data.customer_email:
                known_user = self.db.scalar(select(UserModel).where(UserModel.email == data.customer_email, UserModel.is_active.is_(True)))
            items = []
            total = Decimal(0)
            stock = StockService(self.db)
            for line in sorted(data.items, key=lambda row: str(row.variant_id)):
                variant = self.variant(line.variant_id)
                snapshot = self.snapshot(variant, line.quantity, data.branch_id)
                stock.change(line.variant_id, data.branch_id, -line.quantity, "pos_sale",
                    "Salida por venta presencial cobrada.", reference="venta-en-caja", actor_id=actor.id)
                items.append(snapshot)
                total += Decimal(snapshot["line_total"])
            now = datetime.now(timezone.utc)
            order = OrderModel(
                number="FS-" + uuid.uuid4().hex[:12].upper(), user_id=known_user.id if known_user else None,
                customer_email=data.customer_email or "", branch_id=data.branch_id,
                sales_channel="pos", cash_point_id=cash_point.id, cashier_user_id=actor.id,
                client_request_id=data.client_request_id, request_fingerprint=fingerprint,
                status="delivered", payment_status="paid", payment_method=data.payment_method,
                payment_reference=data.payment_reference, total=total, currency=settings.commerce_currency,
                address={"recipient": data.customer_name, "channel": "pos"}, items=items,
                tracking=[{"status": "delivered", "note": "Venta presencial cobrada y entregada en caja.", "date": now.isoformat()}],
                paid_at=now,
            )
            self.db.add(order)
            self.db.flush()
            self.audit(order, "pos_sale_created", "Venta presencial registrada, cobrada y entregada.")
            self.db.commit()
            self.db.refresh(order)
            # Solo sale si el cajero cargo un correo; la venta presencial no lo exige.
            notificar_pedido(self.db, order, "Comprobante de tu compra en caja.")
            return order, False
        except Exception:
            self.db.rollback()
            raise

    def tracking(self, order, data):
        if data.status not in TRANSITIONS.get(order.status, set()):
            raise ConflictError("Transicion de seguimiento no permitida.")
        if data.status == "shipped" and not (data.carrier and data.tracking_number):
            raise ValidationError("Indique transportista y numero de seguimiento.")
        order.status = data.status
        order.carrier = data.carrier or order.carrier
        order.tracking_number = data.tracking_number or order.tracking_number
        self.track(order, data.note or "Estado actualizado por administracion.")
        self.audit(order, "tracking_updated", "Seguimiento del pedido actualizado.")
        self.db.commit()
        notificar_pedido(self.db, order, data.note)
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
        estado_previo = order.status
        if order.status == "pending_payment":
            if event["type"] == "checkout.session.expired":
                self.release(order, "expired")
            elif session.get("payment_status") == "paid":
                self.confirm_stripe_payment(order, session,
                    "Pago de prueba confirmado por webhook firmado de Stripe.", event.get("created"))
        self.db.add(WebhookEventModel(event_id=event["id"]))
        self.audit(order, "stripe_event", "Evento de Stripe de prueba verificado.")
        self.db.commit()
        # Solo se avisa si el evento movio el pedido: Stripe reintenta y el
        # cliente no deberia recibir el mismo correo dos veces.
        if order.status != estado_previo:
            notificar_pedido(self.db, order)
        return {"received": True}
