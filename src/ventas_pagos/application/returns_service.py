"""Registro y resolución de devoluciones (CU19).

El cliente pide devolver prendas de un pedido entregado; administración aprueba
o rechaza, y al completarse las unidades vuelven al stock de la sucursal con su
movimiento de inventario, igual que cualquier otra entrada.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.notificaciones.application.use_cases.send_notification import notificar_devolucion
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError, ValidationError
from src.ventas_pagos.application.stock_service import StockService
from src.ventas_pagos.domain import returns
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.ventas_pagos.infrastructure.models import OrderModel, OrderReturnModel


class ReturnsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Consulta --------------------------------------------------------

    def del_pedido(self, order_id) -> list[OrderReturnModel]:
        return list(self.db.scalars(
            select(OrderReturnModel).where(OrderReturnModel.order_id == order_id)
            .order_by(OrderReturnModel.created_at.desc())
        ))

    def mias(self, user, limit: int = 100, offset: int = 0) -> list[OrderReturnModel]:
        return list(self.db.scalars(
            select(OrderReturnModel).where(OrderReturnModel.user_id == user.id)
            .order_by(OrderReturnModel.created_at.desc()).offset(offset).limit(limit)
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
        devolucion = self.db.get(OrderReturnModel, return_id)
        if not devolucion or (user is not None and devolucion.user_id != user.id):
            raise NotFoundError("Devolucion no encontrada.")
        return devolucion

    def devolvible(self, order) -> dict:
        """Qué puede devolver el cliente de este pedido, y si no puede, por qué."""
        motivo = returns.motivo_para_rechazar(order)
        disponibles = returns.unidades_devolvibles(order, self.del_pedido(order.id))
        return {
            "can_request": motivo is None and bool(disponibles),
            "reason": motivo or (None if disponibles else "Ya solicitaste la devolución de todas las prendas."),
            "units": disponibles,
        }

    # --- Alta ------------------------------------------------------------

    def solicitar(self, user, order: OrderModel, data) -> OrderReturnModel:
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
                order, self.del_pedido(order.id),
                [(str(item.variant_id), item.quantity) for item in data.items],
            )
        except ValueError as error:
            raise ValidationError(str(error)) from error
        devolucion = OrderReturnModel(
            order_id=order.id, user_id=order.user_id or (user.id if user else None),
            branch_id=order.branch_id, status="requested", reason=data.reason.strip(),
            items=detalle, refund_amount=Decimal(returns.monto(detalle)), currency=order.currency,
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
                order, self.del_pedido(order.id),
                [(str(item.variant_id), item.quantity) for item in data.items],
            )
        except ValueError as error:
            raise ValidationError(str(error)) from error

        ahora = datetime.now(timezone.utc)
        devolucion = OrderReturnModel(
            order_id=order.id, user_id=order.user_id, branch_id=order.branch_id,
            status="completed", reason=data.reason.strip(), items=detalle,
            refund_amount=Decimal(returns.monto(detalle)), currency=order.currency,
            resolution_note=(data.note or "").strip() or "Devolución atendida en caja.",
            resolved_at=ahora, resolved_by=actor.id, client_request_id=data.client_request_id,
        )
        try:
            inventario = StockService(self.db)
            for item in sorted(detalle, key=lambda row: str(row["variant_id"])):
                inventario.change(
                    uuid.UUID(item["variant_id"]), order.branch_id, int(item["quantity"]),
                    "return_received", "Prendas recibidas en una devolución de mostrador.",
                    reference=order.number, actor_id=actor.id,
                )
            self.db.add(devolucion)
            self.db.flush()
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
        if data.status not in returns.TRANSICIONES.get(devolucion.status, set()):
            raise ConflictError(
                f"No se puede pasar una devolucion de '{devolucion.status}' a '{data.status}'."
            )
        order = self.db.get(OrderModel, devolucion.order_id)
        try:
            if data.status == "completed":
                # Las prendas vuelven recién cuando se reciben físicamente.
                inventario = StockService(self.db)
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
