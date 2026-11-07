"""Registro y resolución de devoluciones (CU19).

El cliente pide devolver prendas de un pedido entregado; administración aprueba
o rechaza, y al completarse las unidades vuelven al stock de la sucursal con su
movimiento de inventario, igual que cualquier otra entrada.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.notificaciones.application.use_cases.send_notification import notificar_devolucion
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError, ValidationError
from src.ventas_pagos.application.stock_service import StockService
from src.ventas_pagos.infrastructure import gateways
from src.ventas_pagos.domain import returns
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.ventas_pagos.infrastructure.models import OrderModel, OrderReturnModel, StockModel
from src.usuarios_catalogo.infrastructure.models.catalog import ProductVariantModel, ProductModel
from src.ventas_pagos.infrastructure.exchange_models import GarmentExchangeModel
from src.ventas_pagos.application.exchange_settlement import ExchangeSettlement
from src.ventas_pagos.application.pricing_service import PricingService
from src.plataforma_saas.infrastructure.models.tenant import TenantModel


class ReturnsService:
    def __init__(self, db: Session, tenant_id: uuid.UUID | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id

    # --- Consulta --------------------------------------------------------

    def del_pedido(self, order_id) -> list[OrderReturnModel]:
        query = select(OrderReturnModel).where(OrderReturnModel.order_id == order_id)
        if self.tenant_id is not None:
            query = query.where(OrderReturnModel.tenant_id == self.tenant_id)
        return list(self.db.scalars(
            query.order_by(OrderReturnModel.created_at.desc())
        ))

    def mias(self, user, limit: int = 100, offset: int = 0) -> list[OrderReturnModel]:
        query = select(OrderReturnModel).where(OrderReturnModel.user_id == user.id)
        if self.tenant_id is not None:
            query = query.where(OrderReturnModel.tenant_id == self.tenant_id)
        return list(self.db.scalars(
            query.order_by(OrderReturnModel.created_at.desc()).offset(offset).limit(limit)
        ))

    def todas(
        self,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        branch_id=None,
        q: str | None = None,
    ) -> list[OrderReturnModel]:
        """Bandeja de administración, con los filtros que se usan para trabajar.

        Sin filtros la lista se vuelve inservible apenas hay movimiento: quien
        atiende devoluciones trabaja por sucursal y por estado, no leyendo todo.
        """
        consulta = select(OrderReturnModel)
        if self.tenant_id is not None:
            consulta = consulta.where(OrderReturnModel.tenant_id == self.tenant_id)
        if status:
            consulta = consulta.where(OrderReturnModel.status == status)
        if branch_id:
            consulta = consulta.where(OrderReturnModel.branch_id == branch_id)
        if q:
            # Se busca por el número del pedido, que es lo que trae el cliente.
            texto = f"%{q.strip().upper()}%"
            consulta = consulta.join(
                OrderModel, OrderModel.id == OrderReturnModel.order_id
            ).where(OrderModel.number.ilike(texto))
        return list(self.db.scalars(
            consulta.order_by(OrderReturnModel.created_at.desc()).offset(offset).limit(limit)
        ))

    def enriquecer(self, devoluciones: list[OrderReturnModel]) -> dict[str, dict]:
        """Datos del pedido y de la sucursal, por devolución.

        Una devolución sola no se puede gestionar: en pantalla hay que ver de
        qué pedido viene, de quién es y en qué sucursal se atiende. Se resuelve
        en dos consultas y no una por fila.
        """
        if not devoluciones:
            return {}
        pedidos = {
            o.id: o for o in self.db.scalars(
                select(OrderModel).where(OrderModel.id.in_({d.order_id for d in devoluciones}))
            )
        }
        sucursales = {
            b.id: b for b in self.db.scalars(
                select(BranchModel).where(BranchModel.id.in_({d.branch_id for d in devoluciones}))
            )
        }
        contexto: dict[str, dict] = {}
        for devolucion in devoluciones:
            pedido = pedidos.get(devolucion.order_id)
            sucursal = sucursales.get(devolucion.branch_id)
            contexto[str(devolucion.id)] = {
                "order_number": pedido.number if pedido else None,
                "customer_email": pedido.customer_email if pedido else None,
                "customer_name": (pedido.address or {}).get("recipient") if pedido else None,
                "sales_channel": pedido.sales_channel if pedido else None,
                "branch_name": sucursal.name if sucursal else None,
            }
        return contexto

    def obtener(self, return_id, user=None) -> OrderReturnModel:
        query = select(OrderReturnModel).where(OrderReturnModel.id == return_id)
        if user is not None:
            query = query.where(OrderReturnModel.user_id == user.id)
        if self.tenant_id is not None:
            query = query.where(OrderReturnModel.tenant_id == self.tenant_id)
        devolucion = self.db.scalar(query)
        if not devolucion:
            raise NotFoundError("Devolucion no encontrada.")
        return devolucion

    def devolvible(self, order) -> dict:
        """Qué puede devolver el cliente de este pedido, y si no puede, por qué."""
        motivo = returns.motivo_para_rechazar(order)
        disponibles = returns.unidades_devolvibles(order, self.compromisos(order))
        return {
            'can_exchange': self.motivo_cambio(order) is None and bool(disponibles),
            'exchange_reason': self.motivo_cambio(order),
            "can_request": motivo is None and bool(disponibles),
            "reason": motivo or (None if disponibles else "Ya solicitaste la devolución de todas las prendas."),
            "units": disponibles,
        }

    def motivo_cambio(self, order):
        from datetime import timedelta
        if order.status != 'delivered' or order.payment_status != 'paid':
            return 'Solo se cambian prendas de pedidos pagados y entregados.'
        tenant=self.db.get(TenantModel,order.tenant_id)
        days=tenant.exchange_days if tenant else 15
        delivered=returns.fecha_de_entrega(order) or order.paid_at or order.created_at
        if delivered.tzinfo is None:
            delivered=delivered.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc)-delivered>timedelta(days=days):
            return f'El plazo de {days} días para cambios ya venció.'
        return None

    def compromisos(self, order):
        """Both customer requests and completed counter exchanges consume units."""
        from types import SimpleNamespace
        result = list(self.del_pedido(order.id))
        for exchange in self.db.scalars(select(GarmentExchangeModel).where(
            GarmentExchangeModel.tenant_id == order.tenant_id,
            GarmentExchangeModel.original_order_id == order.id,
            GarmentExchangeModel.status != 'CANCELLED',
        )):
            result.append(SimpleNamespace(status='completed', items=[{
                'variant_id': str(line.original_variant_id), 'quantity': line.returned_quantity,
            } for line in exchange.lines]))
        return result

    @staticmethod
    def es_cambio(devolucion: OrderReturnModel) -> bool:
        return bool(devolucion.items and devolucion.items[0].get("replacement_variant_id"))

    def monto_a_reintegrar(self, order: OrderModel, detalle: list[dict]) -> Decimal:
        """Distribuye el descuento pagado y nunca reintegra más que el total cobrado."""
        bruto = sum((Decimal(row["line_total"]) for row in detalle), Decimal(0))
        subtotal = Decimal(order.subtotal or 0)
        if subtotal <= 0:
            subtotal = sum((Decimal(str(row.get('line_total', Decimal(str(row.get('unit_price',0)))*int(row.get('quantity',0))))) for row in order.items), Decimal(0))
        total = Decimal(order.total)
        if subtotal <= 0 or total <= 0:
            return Decimal("0.00")
        commitments=self.compromisos(order)
        importe=sum((returns.paid_credit(order,row['variant_id'],int(row['quantity']),commitments) for row in detalle),Decimal(0))
        comprometido = sum((
            Decimal(row.refund_amount) for row in self.del_pedido(order.id)
            if row.status in returns.VIGENTES
        ), Decimal(0))
        return max(Decimal("0.00"), min(importe, total - comprometido))

    def opciones_cambio(self, order: OrderModel, variant_id) -> list[dict]:
        """Available replacements and server-calculated price differences."""
        original = next((i for i in order.items if str(i["variant_id"]) == str(variant_id)), None)
        if not original:
            raise ValidationError("La prenda no pertenece al pedido.")
        detalle = returns.armar_detalle(order, [], [(str(variant_id), 1)])
        precio = self.monto_a_reintegrar(order, detalle)
        rows = self.db.execute(select(ProductVariantModel, StockModel.quantity).join(
            StockModel, StockModel.variant_id == ProductVariantModel.id
        ).join(ProductModel, ProductModel.id == ProductVariantModel.product_id).where(
            StockModel.branch_id == order.branch_id, StockModel.quantity > 0,
            ProductModel.tenant_id == order.tenant_id,
            ProductVariantModel.is_active.is_(True), ProductModel.is_active.is_(True),
            ProductModel.deleted_at.is_(None), ProductVariantModel.id != variant_id,
        )).all()
        pricing=PricingService(self.db,order.tenant_id)
        return [{
            "variant_id": str(variant.id), "product_name": variant.product.name,
            "size": variant.size.name, "color": variant.color.name,
            "available": quantity, "price": str(pricing.precio(variant,canal='ONLINE').final),
            "original_credit": str(precio),
            "difference": str(pricing.precio(variant,canal='ONLINE').final - precio),
        } for variant, quantity in rows]

    def solicitar_cambio(self, user, order: OrderModel, data) -> OrderReturnModel:
        order = self.db.scalar(select(OrderModel).where(OrderModel.id == order.id)
            .with_for_update().execution_options(populate_existing=True))
        existente = self.db.scalar(select(OrderReturnModel).where(
            OrderReturnModel.client_request_id == data.client_request_id
        ))
        if existente:
            if existente.order_id != order.id or not self.es_cambio(existente):
                raise ConflictError("Esa clave ya corresponde a otra solicitud.")
            item = existente.items[0]
            if (item["variant_id"] != str(data.variant_id)
                    or item["replacement_variant_id"] != str(data.replacement_variant_id)
                    or int(item["quantity"]) != data.quantity
                    or existente.reason != data.reason.strip()):
                raise ConflictError("La clave ya fue usada para otro cambio.")
            return existente
        motivo = self.motivo_cambio(order)
        if motivo:
            raise ConflictError(motivo)
        if data.variant_id == data.replacement_variant_id:
            raise ValidationError("Elegí una prenda o talla diferente.")
        try:
            detalle = returns.armar_detalle(
                order, self.compromisos(order), [(str(data.variant_id), data.quantity)]
            )
        except ValueError as error:
            raise ValidationError(str(error)) from error
        opciones = {row["variant_id"]: row for row in self.opciones_cambio(order, data.variant_id)}
        opcion = opciones.get(str(data.replacement_variant_id))
        if not opcion:
            raise ConflictError("La prenda elegida ya no está disponible en esta sucursal.")
        detalle[0]["replacement_variant_id"] = str(data.replacement_variant_id)
        detalle[0]["replacement_name"] = opcion["product_name"]
        detalle[0]["replacement_size"] = opcion["size"]
        detalle[0]["replacement_color"] = opcion["color"]
        detalle[0]["replacement_unit_price"] = opcion["price"]
        credit = self.monto_a_reintegrar(order, detalle)
        difference = (Decimal(opcion['price']) * data.quantity - credit).quantize(Decimal('.01'))
        detalle[0]['original_credit'] = str(credit)
        cambio = OrderReturnModel(
            tenant_id=order.tenant_id,
            order_id=order.id, user_id=order.user_id or user.id, branch_id=order.branch_id,
            status="requested", reason=data.reason.strip(), items=detalle,
            refund_amount=max(Decimal(0), -difference), currency=order.currency,
            difference_amount=difference,
            settlement_status='payment_pending' if difference > 0 else 'refund_pending' if difference < 0 else 'not_required',
            client_request_id=data.client_request_id,
        )
        try:
            StockService(self.db, self.tenant_id or order.tenant_id).change(
                data.replacement_variant_id, order.branch_id, -data.quantity,
                "exchange_hold", "Prenda apartada para un cambio solicitado.",
                reference=order.number, actor_id=user.id,
            )
            self.db.add(cambio)
            self.db.flush()
            RecordAuditEvent(self.db).execute(
                action="commerce.exchange_requested", entity_type="order_return",
                entity_id=str(cambio.id), description="Cambio solicitado por el cliente.",
                actor_user_id=user.id, metadata={"order": order.number},
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(cambio)
        notificar_devolucion(self.db, cambio, order, avisar_gestion=True)
        return cambio

    # --- Alta ------------------------------------------------------------

    def solicitar(self, user, order: OrderModel, data) -> OrderReturnModel:
        order = self.db.scalar(select(OrderModel).where(OrderModel.id == order.id)
            .with_for_update().execution_options(populate_existing=True))
        if data.client_request_id:
            existente = self.db.scalar(select(OrderReturnModel).where(
                OrderReturnModel.client_request_id == data.client_request_id))
            if existente:
                # Reenvío del mismo formulario: se devuelve lo ya registrado.
                if existente.order_id != order.id:
                    raise ConflictError("Esa clave ya corresponde a otra devolución.")
                return existente
        motivo = returns.motivo_para_rechazar(order)
        if motivo:
            raise ConflictError(motivo)
        try:
            detalle = returns.armar_detalle(
                order, self.compromisos(order),
                [(str(item.variant_id), item.quantity) for item in data.items],
            )
        except ValueError as error:
            raise ValidationError(str(error)) from error
        devolucion = OrderReturnModel(
            tenant_id=order.tenant_id,
            order_id=order.id, user_id=order.user_id or (user.id if user else None),
            branch_id=order.branch_id, status="requested", reason=data.reason.strip(),
            items=detalle, refund_amount=self.monto_a_reintegrar(order, detalle), currency=order.currency,
            client_request_id=data.client_request_id,
        )
        self.db.add(devolucion)
        self.db.flush()
        RecordAuditEvent(self.db).execute(
            action="commerce.return_requested", entity_type="order_return",
            entity_id=str(devolucion.id), description="Devolucion solicitada por el cliente.",
            actor_user_id=user.id if user else None,
            metadata={"order": order.number, "amount": str(devolucion.refund_amount)},
        )
        self.db.commit()
        self.db.refresh(devolucion)
        # Al cliente, para que sepa que la recibimos; y a gestion, porque una
        # solicitud sin revisar es un cliente esperando y stock inmovilizado.
        notificar_devolucion(self.db, devolucion, order, avisar_gestion=True)
        return devolucion

    def registrar_en_caja(self, actor, order: OrderModel, data) -> OrderReturnModel:
        """Devolución en mostrador: se resuelve en un solo paso (CU19, RF17).

        En el mostrador el cliente entrega la prenda y se le reintegra el dinero
        en el momento. El circuito de tres pasos del canal web —solicitar,
        aprobar, recibir— no aplica: acá las tres cosas ocurren juntas, así que
        la devolución nace cerrada y las unidades vuelven al stock enseguida.
        """
        order = self.db.scalar(select(OrderModel).where(OrderModel.id == order.id)
            .with_for_update().execution_options(populate_existing=True))
        if data.client_request_id:
            existente = self.db.scalar(select(OrderReturnModel).where(
                OrderReturnModel.client_request_id == data.client_request_id))
            if existente:
                if existente.order_id != order.id:
                    raise ConflictError("Esa clave ya corresponde a otra devolución.")
                return existente
        motivo = returns.motivo_para_rechazar(order)
        if motivo:
            raise ConflictError(motivo)
        try:
            detalle = returns.armar_detalle(
                order, self.compromisos(order),
                [(str(item.variant_id), item.quantity) for item in data.items],
            )
        except ValueError as error:
            raise ValidationError(str(error)) from error

        ahora = datetime.now(timezone.utc)
        devolucion = OrderReturnModel(
            tenant_id=order.tenant_id,
            order_id=order.id, user_id=order.user_id, branch_id=order.branch_id,
            status="completed", reason=data.reason.strip(), items=detalle,
            refund_amount=self.monto_a_reintegrar(order, detalle), currency=order.currency,
            resolution_note=(data.note or "").strip() or "Devolución atendida en caja.",
            resolved_at=ahora, resolved_by=actor.id, client_request_id=data.client_request_id,
        )
        try:
            inventario = StockService(self.db, self.tenant_id or order.tenant_id)
            for item in sorted(detalle, key=lambda row: str(row["variant_id"])):
                inventario.change(
                    uuid.UUID(item["variant_id"]), order.branch_id, int(item["quantity"]),
                    "return_received", "Prendas recibidas en una devolución de mostrador.",
                    reference=order.number, actor_id=actor.id,
                )
            self.db.add(devolucion)
            self.db.flush()
            if order.payment_method == 'stripe' and devolucion.refund_amount > 0:
                devolucion.settlement_reference = gateways.refund_order_return(order, devolucion,
                    **gateways.en_cuenta(order.stripe_account_id))
                devolucion.settlement_method = 'stripe'
                devolucion.settlement_status = 'refunded'
            RecordAuditEvent(self.db).execute(
                action="commerce.return_completed", entity_type="order_return",
                entity_id=str(devolucion.id),
                description="Devolucion registrada y reintegrada en caja.",
                actor_user_id=actor.id,
                metadata={"order": order.number, "amount": str(devolucion.refund_amount),
                          "canal": "pos"},
            )
            self.db.commit()
        except Exception:
            # Si falla una prenda no se reintegra nada: la caja no puede quedar
            # con media devolución registrada.
            self.db.rollback()
            raise
        self.db.refresh(devolucion)
        notificar_devolucion(self.db, devolucion, order)
        return devolucion

    # --- Resolución ------------------------------------------------------

    def resolver(self, actor, devolucion: OrderReturnModel, data) -> OrderReturnModel:
        if self.tenant_id and devolucion.tenant_id != self.tenant_id:
            raise NotFoundError("Devolucion no encontrada.")
        # Shared lock order for all returns/exchanges: order, request, stock.
        self.db.scalar(select(OrderModel.id).where(OrderModel.id == devolucion.order_id).with_for_update())
        devolucion = self.db.scalar(select(OrderReturnModel).where(
            OrderReturnModel.id == devolucion.id
        ).with_for_update().execution_options(populate_existing=True))
        if data.status == devolucion.status:
            return devolucion
        if data.status not in returns.TRANSICIONES.get(devolucion.status, set()):
            raise ConflictError(
                f"No se puede pasar una devolucion de '{devolucion.status}' a '{data.status}'."
            )
        order = self.db.get(OrderModel, devolucion.order_id)
        try:
            if data.status == "rejected" and self.es_cambio(devolucion):
                ExchangeSettlement(self.db).before_reject(devolucion)
                item = devolucion.items[0]
                StockService(self.db, self.tenant_id or devolucion.tenant_id).change(
                    uuid.UUID(item["replacement_variant_id"]), devolucion.branch_id,
                    int(item["quantity"]), "exchange_release",
                    "Prenda liberada por cambio rechazado.",
                    reference=order.number if order else str(devolucion.order_id),
                    actor_id=actor.id,
                )
            if data.status == "completed":
                if self.es_cambio(devolucion):
                    ExchangeSettlement(self.db).complete(devolucion, order, data)
                if (order and order.payment_method == "stripe"
                        and not self.es_cambio(devolucion)
                        and devolucion.refund_amount > 0):
                    # El reembolso sale de la misma cuenta conectada que cobró el pedido.
                    gateways.refund_order_return(order, devolucion, **gateways.en_cuenta(order.stripe_account_id))
                # Las prendas vuelven recién cuando se reciben físicamente.
                inventario = StockService(self.db, self.tenant_id or devolucion.tenant_id)
                for item in sorted(devolucion.items, key=lambda row: str(row["variant_id"])):
                    inventario.change(
                        uuid.UUID(item["variant_id"]), devolucion.branch_id, int(item["quantity"]),
                        "return_received", "Prendas recibidas por una devolucion aprobada.",
                        reference=order.number if order else str(devolucion.order_id),
                        actor_id=actor.id,
                    )
            devolucion.status = data.status
            devolucion.resolution_note = (data.note or "").strip() or None
            devolucion.resolved_at = datetime.now(timezone.utc)
            devolucion.resolved_by = actor.id
            RecordAuditEvent(self.db).execute(
                action=f"commerce.return_{data.status}", entity_type="order_return",
                entity_id=str(devolucion.id), description="Devolucion resuelta por administracion.",
                actor_user_id=actor.id,
                metadata={"status": data.status, "amount": str(devolucion.refund_amount)},
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(devolucion)
        if order:
            notificar_devolucion(self.db, devolucion, order)
        return devolucion
