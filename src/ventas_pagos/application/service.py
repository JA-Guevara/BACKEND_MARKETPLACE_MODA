import uuid
import hashlib
import json
from datetime import date, datetime, timezone
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
from src.ventas_pagos.application.pricing_service import PricingService
from src.ventas_pagos.application.promotions import PromotionService
from src.ventas_pagos.infrastructure.engagement_models import PromotionModel, PromotionUseModel
from src.notificaciones.application.use_cases.send_notification import notificar_pedido


class CommerceService:
    def __init__(self, db: Session, tenant_id: uuid.UUID | None = None):
        self.db = db
        self.tenant_id = tenant_id

    def audit(self, order, action, description):
        RecordAuditEvent(self.db).execute(action="commerce." + action, entity_type="order", entity_id=str(order.id), description=description, metadata={"number":order.number,"status":order.status,"payment_status":order.payment_status})

    def _publicar(self, order, event_type):
        from src.integraciones.application.webhooks_service import WebhooksService
        service = WebhooksService(self.db)
        service.publicar_si_hay_suscriptores(order.tenant_id, event_type, {
            "order_id": str(order.id), "number": order.number, "total": str(order.total),
            "currency": order.currency, "branch_id": str(order.branch_id),
        })

    def branch(self, branch_id):
        branch = self.db.get(BranchModel, branch_id)
        if not branch or branch.deleted_at:
            raise NotFoundError("Sucursal no encontrada.")
        if self.tenant_id and branch.tenant_id != self.tenant_id:
            raise NotFoundError("Sucursal no pertenece a la empresa.")
        if not branch.is_active:
            raise ValidationError("Sucursal no disponible.")
        return branch

    def variant(self, variant_id):
        variant = self.db.get(ProductVariantModel, variant_id)
        if not variant or not variant.is_active or not variant.product or not variant.product.is_active or variant.product.deleted_at:
            raise NotFoundError("La variante no esta disponible.")
        if self.tenant_id and variant.product.tenant_id != self.tenant_id:
            raise NotFoundError("La variante no pertenece a la empresa.")
        return variant

    def snapshot(self, variant, quantity, branch_id, canal="ONLINE"):
        stock = self.db.scalar(select(StockModel).where(StockModel.variant_id == variant.id, StockModel.branch_id == branch_id)) if branch_id else None
        t_id = self.tenant_id or variant.product.tenant_id
        pv = PricingService(self.db, t_id).precio(variant, canal=canal)
        price = pv.final
        return {
            "variant_id": str(variant.id), "product_id": str(variant.product_id), "name": variant.product.name,
            "sku": variant.sku, "size": variant.size.name, "color": variant.color.name,
            "category_id": str(variant.product.category_id),
            "image_url": variant.product.images[0].url if variant.product.images else None,
            "unit_price": str(price), "regular_price": str(pv.regular), "quantity": quantity,
            "available": stock.quantity if stock else 0,
            "line_total": str(price * quantity),
            "offer_id": pv.offer_id, "offer_name": pv.offer_name,
        }

    def cart(self, user, branch_id=None, coupon_code=None):
        rows = self.db.scalars(select(CartItemModel).where(CartItemModel.user_id == user.id)).all()
        items = []
        for row in rows:
            variant = self.db.get(ProductVariantModel, row.variant_id)
            if variant is None:
                continue
            if self.tenant_id and variant.product.tenant_id != self.tenant_id:
                continue
            item = self.snapshot(variant, row.quantity, branch_id)
            if not variant.is_active or not variant.product.is_active or variant.product.deleted_at:
                item["available"] = 0
            items.append(item)
        quote = PromotionService(self.db, self.tenant_id).quote(user, items, coupon_code)
        return {"items": items, "currency": settings.commerce_currency, **quote}

    def recommendations(self, user, limit: int = 8, *, branch_id=None, size_id=None,
                        season_id=None, product_id=None):
        """RF25/CU23: ordena prendas disponibles según cliente y contexto.

        El stock se consulta de nuevo en cada petición. Es una sugerencia, no
        una reserva: el checkout vuelve a comprobarlo con bloqueo.
        """
        disponibles = select(ProductVariantModel.product_id).join(
            StockModel, StockModel.variant_id == ProductVariantModel.id
        ).where(ProductVariantModel.is_active.is_(True), StockModel.quantity > 0)
        if branch_id:
            disponibles = disponibles.where(StockModel.branch_id == branch_id)
        if size_id:
            disponibles = disponibles.where(ProductVariantModel.size_id == size_id)
        query = select(ProductModel).where(
            ProductModel.is_active.is_(True), ProductModel.deleted_at.is_(None),
            ProductModel.id.in_(disponibles),
        )
        if self.tenant_id:
            query = query.where(ProductModel.tenant_id == self.tenant_id)
        if season_id:
            query = query.where(ProductModel.season_id == season_id)
        if product_id:
            query = query.where(ProductModel.id != product_id)

        purchased_ids: set[uuid.UUID] = set()
        preferred_categories: set[uuid.UUID] = set()
        preferred_size_products: set[uuid.UUID] = set()
        if user is not None:
            order_query = select(OrderModel).where(
                OrderModel.user_id == user.id, OrderModel.payment_status == "paid"
            )
            if self.tenant_id:
                order_query = order_query.where(OrderModel.tenant_id == self.tenant_id)
            paid_orders = self.db.scalars(order_query).all()
            purchased_ids = {
                uuid.UUID(item["product_id"]) for order in paid_orders
                for item in order.items if item.get("product_id")
            }
            purchased_variants = {
                uuid.UUID(item["variant_id"]) for order in paid_orders
                for item in order.items if item.get("variant_id")
            }
            if purchased_variants:
                variants = self.db.scalars(
                    select(ProductVariantModel).where(ProductVariantModel.id.in_(purchased_variants))
                ).all()
                preferred_categories = {v.product.category_id for v in variants if v.product}
                size_ids = {v.size_id for v in variants if v.size_id}
                if size_ids:
                    size_product_rows = self.db.scalars(
                        select(ProductVariantModel.product_id).where(
                            ProductVariantModel.size_id.in_(size_ids),
                            ProductVariantModel.is_active.is_(True),
                        )
                    ).all()
                    preferred_size_products = set(size_product_rows)

        def score(product: ProductModel) -> tuple:
            # 1. No comprada antes
            novelty = 1 if product.id not in purchased_ids else 0
            # 2. Misma categoría que compras previas
            cat_match = 1 if product.category_id in preferred_categories else 0
            # 3. Disponible en una talla que el cliente ya compró
            size_match = 1 if product.id in preferred_size_products else 0
            # 4. Antigüedad (más nuevo primero)
            return (
                novelty,
                cat_match,
                size_match,
                product.created_at.isoformat() if product.created_at else "",
            )

        products = sorted(self.db.scalars(query).all(), key=score, reverse=True)[:limit]
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
        if self.tenant_id is not None:
            query = query.where(OrderModel.tenant_id == self.tenant_id)
        order = self.db.scalar(query.with_for_update())
        if not order:
            raise NotFoundError("Pedido no encontrado.")
        return order

    def create_order(self, user, data):
        branch = self.branch(data.branch_id)
        order_tenant_id = self.tenant_id or branch.tenant_id
        self.db.execute(select(UserModel.id).where(UserModel.id == user.id).with_for_update())
        # Se calcula nuevamente con bloqueo: no se confía ni en el total ni en
        # un cupón que pudo caducar entre la pantalla de carrito y el pago.
        cart = self.cart(user, data.branch_id, data.coupon_code)
        quote = PromotionService(self.db, order_tenant_id).quote(user, cart["items"], data.coupon_code, lock=True)
        cart.update(quote)
        if not cart["items"]:
            raise ValidationError("El carrito esta vacio.")
        if data.payment_method == "stripe" and Decimal(quote["total"]) > 0:
            from src.plataforma_saas.application.stripe_connect_service import CardPaymentsUnavailableError, tarjeta_disponible
            if not tarjeta_disponible(self.db, order_tenant_id):
                raise CardPaymentsUnavailableError()
        try:
            stock_svc = StockService(self.db, order_tenant_id)
            for item in sorted(cart["items"], key=lambda x: x["variant_id"]):
                self.variant(uuid.UUID(item["variant_id"]))
                stock_svc.change(uuid.UUID(item["variant_id"]), data.branch_id,
                    -item["quantity"], "web_order_hold", "Existencias reservadas para pedido web.",
                    reference="nuevo-pedido", actor_id=user.id)
            order = OrderModel(
                tenant_id=order_tenant_id,
                number="FS-" + uuid.uuid4().hex[:12].upper(), user_id=user.id,
                branch_id=data.branch_id, customer_email=user.email, payment_method=data.payment_method,
                sales_channel=data.channel,
                total=Decimal(cart["total"]), subtotal=Decimal(cart["subtotal"]),
                discount_total=Decimal(cart["discount_total"]), discounts=cart["discounts"],
                coupon_code=cart["coupon_code"], currency=cart["currency"], address=data.address.model_dump(), items=cart["items"],
                tracking=[{"status": "pending_payment", "note": "Pedido creado; existencias reservadas.", "date": datetime.now(timezone.utc).isoformat()}])
            if order.total == 0:
                order.status = "paid"
                order.payment_status = "paid"
                order.paid_at = datetime.now(timezone.utc)
                self.track(order, "Pedido cubierto íntegramente por descuentos; no requiere cobro.")
            self.db.add(order)
            self.db.flush()
            PromotionService(self.db, order_tenant_id).record_uses(user, order, quote)
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
        stock_svc = StockService(self.db, order.tenant_id)
        for item in sorted(order.items, key=lambda row: row["variant_id"]):
            stock_svc.change(uuid.UUID(item["variant_id"]), order.branch_id,
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
            gateways.stripe_request("POST", f"checkout/sessions/{order.stripe_session_id}/expire",
                                    **gateways.en_cuenta(order.stripe_account_id))
        self.release(order, "cancelled")
        self.audit(order, "order_cancelled", "Pedido cancelado; existencias liberadas.")
        self.db.commit()
        notificar_pedido(self.db, order)
        return order

    def checkout(self, order, payment_return_url=None):
        if order.payment_method == "stripe" and order.stripe_session_id:
            self.reconcile_payment(order)
        if order.payment_status == "paid":
            return {"status": order.status, "url": None}
        if order.status != "pending_payment" or order.payment_method != "stripe":
            raise ConflictError("Pedido no disponible para pago con Stripe.")
        if not order.stripe_session_id:
            # Cargo directo en la cuenta Connect de la empresa del pedido (RN-ST1/RN-ST2);
            # sin cuenta activa, 409 card_payments_unavailable y la tienda ofrece QR/transferencia.
            from src.plataforma_saas.application.stripe_connect_service import cuenta_para_cobrar
            account_id = cuenta_para_cobrar(self.db, order.tenant_id)
            session = gateways.create_session(order, payment_return_url=payment_return_url, stripe_account=account_id)
            order.stripe_account_id = account_id
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
        self._publicar(order, "order.paid")
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
        session = gateways.retrieve_session(order.stripe_session_id, **gateways.en_cuenta(order.stripe_account_id))
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
        self._publicar(order, "order.paid")
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
            branch = self.branch(data.branch_id)
            order_tenant_id = self.tenant_id or branch.tenant_id
            if cash_point.tenant_id != order_tenant_id:
                raise ValidationError("El punto de caja no pertenece a la empresa.")
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
            stock = StockService(self.db, order_tenant_id)
            applied_pos_offers: list[tuple[uuid.UUID, Decimal]] = []
            for line in sorted(data.items, key=lambda row: str(row.variant_id)):
                variant = self.variant(line.variant_id)
                snapshot = self.snapshot(variant, line.quantity, data.branch_id, canal="POS")
                stock.change(line.variant_id, data.branch_id, -line.quantity, "pos_sale",
                    "Salida por venta presencial cobrada.", reference="venta-en-caja", actor_id=actor.id)
                items.append(snapshot)
                total += Decimal(snapshot["line_total"])
                if snapshot.get("offer_id") and snapshot.get("regular_price"):
                    reg_p = Decimal(snapshot["regular_price"])
                    unit_p = Decimal(snapshot["unit_price"])
                    diff = (reg_p - unit_p) * line.quantity
                    if diff > 0:
                        applied_pos_offers.append((uuid.UUID(snapshot["offer_id"]), diff))
            now = datetime.now(timezone.utc)
            order = OrderModel(
                tenant_id=order_tenant_id,
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
            for off_id, disc_amount in applied_pos_offers:
                try:
                    p_row = self.db.get(PromotionModel, off_id)
                    if p_row:
                        p_row.uses_count += 1
                        self.db.add(PromotionUseModel(
                            promotion_id=p_row.id,
                            user_id=known_user.id if known_user else actor.id,
                            order_id=order.id,
                            amount=disc_amount,
                            channel="POS",
                        ))
                except Exception:
                    pass
            self._publicar(order, "sale.confirmed")
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
        pickup = bool((order.address or {}).get("pickup"))
        allowed = (
            {"paid": {"processing", "delivered"}, "processing": {"delivered"}}
            if pickup else TRANSITIONS
        )
        if data.status not in allowed.get(order.status, set()) or (pickup and order.payment_status != "paid"):
            raise ConflictError("Transicion de seguimiento no permitida.")
        if data.status == "shipped" and not (data.carrier and data.tracking_number):
            raise ValidationError("Indique transportista y numero de seguimiento.")
        order.status = data.status
        order.carrier = data.carrier or order.carrier
        order.tracking_number = data.tracking_number or order.tracking_number
        self.track(order, data.note or (
            "Retiro en sucursal confirmado por el personal."
            if pickup and data.status == "delivered" else "Estado actualizado por administracion."
        ))
        self.audit(order, "tracking_updated", "Seguimiento del pedido actualizado.")
        self.db.commit()
        notificar_pedido(self.db, order, data.note)
        return order

    def webhook(self, event):
        supported = {"checkout.session.completed", "checkout.session.expired", "checkout.session.async_payment_succeeded"}
        if event.get("type") not in supported:
            return {"received": True}
        session = event["data"]["object"]
        order = self.db.scalar(select(OrderModel).where(OrderModel.stripe_session_id == session["id"], OrderModel.stripe_account_id.is_(None)).with_for_update())
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
