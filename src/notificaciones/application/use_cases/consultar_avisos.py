"""Los avisos que el cliente ve en la campanita.

No hay una tabla de notificaciones: el feed se **deriva** de lo que ya pasó.
Cada pedido, reserva y devolución guarda su propio historial con fecha, así que
inventar una tabla paralela agregaría una migración y una fuente de verdad
duplicada que se puede desincronizar.

Los textos salen de las mismas plantillas que los correos: lo que la persona lee
en la campanita es lo mismo que le llegó al buzón.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.notificaciones.domain.plantillas import (
    ESTADOS_DEVOLUCION,
    ESTADOS_PEDIDO,
    ESTADOS_RESERVA,
)
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.ventas_pagos.infrastructure.models import OrderModel, OrderReturnModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionInvoiceModel
from src.inventario_sucursales.application.services.user_branch_service import UserBranchService

#: Cuántos pedidos/reservas se miran hacia atrás. Más que esto no cabe en una
#: campanita y obliga a leer una base entera para mostrar diez líneas.
VENTANA = 25


def _momento(valor) -> datetime:
    """Fecha comparable. Lo que no se entiende va al fondo, no rompe el orden."""
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    if isinstance(valor, str):
        try:
            leido = datetime.fromisoformat(valor)
            return leido if leido.tzinfo else leido.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def _aviso(*, clave, tipo, estado, titulo, detalle, fecha, enlace, referencia, event_key=None, importante=False, tono="info") -> dict:
    return {
        "id": clave,
        "event_key": event_key or clave,
        "importante": importante,
        "tono": tono,
        "tipo": tipo,
        "estado": estado,
        "titulo": titulo,
        "detalle": detalle,
        "fecha": _momento(fecha).isoformat(),
        "enlace": enlace,
        "referencia": referencia,
    }


class ConsultarAvisos:
    """Arma el feed de avisos de una persona, del más reciente al más viejo."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def execute(self, user: UserModel, limit: int = 20, *, context=None) -> list[dict]:
        self.tenant_id = context.tenant_id if context is not None else user.tenant_id
        self.permissions = context.permissions if context is not None else frozenset()
        self.platform = bool(context and context.is_platform)
        self.support = bool(context and context.is_support)
        self.branches = [b.id for b in UserBranchService(self.db, self.tenant_id).autorizadas(user)] if self.tenant_id else []
        avisos = self._facturacion()
        if self.tenant_id is not None:
            avisos += self._pedidos(user) + self._reservas(user) + self._devoluciones(user)
        avisos.sort(key=lambda a: a["fecha"], reverse=True)
        return avisos[:limit]

    def _scope(self, model, user, permission):
        conditions = [model.tenant_id == self.tenant_id]
        if permission in self.permissions and not self.support:
            conditions.append(model.branch_id.in_(self.branches))
        else:
            conditions.append(model.user_id == user.id)
        return conditions

    def _facturacion(self):
        if self.support or not (
            (self.platform and 'subscriptions.read' in self.permissions) or
            (self.tenant_id and 'my_subscription.read' in self.permissions)
        ):
            return []
        query = select(SubscriptionInvoiceModel)
        if not self.platform:
            query = query.where(SubscriptionInvoiceModel.tenant_id == self.tenant_id)
        invoices = self.db.scalars(query.order_by(SubscriptionInvoiceModel.issued_at.desc()).limit(VENTANA)).all()
        result = []
        now = datetime.now(timezone.utc)
        for invoice in invoices:
            paid = invoice.status == 'paid' and invoice.paid_at is not None
            if invoice.status not in {'issued', 'paid', 'overdue'}:
                continue
            overdue = not paid and invoice.due_at is not None and _momento(invoice.due_at) < now
            state = 'paid' if paid else 'overdue' if overdue else 'issued'
            result.append(_aviso(
                clave=f'billing:{invoice.id}:{state}', tipo='suscripcion', estado=state,
                titulo='Pago del plan confirmado' if paid else 'Pago del plan vencido' if overdue else 'Pago del plan pendiente',
                detalle=f'{invoice.amount:.2f} {invoice.currency} · ' + ('El cobro quedó registrado.' if paid else 'Revisá la factura y sus medios de pago. No se confirmó un cobro.'),
                fecha=invoice.paid_at if paid else invoice.due_at if overdue else invoice.issued_at,
                enlace=f'/admin/plataforma/empresas/{invoice.tenant_id}' if self.platform else '/admin/empresa/suscripcion',
                referencia=invoice.number,
                importante=True, tono='success' if paid else 'warning',
            ))
        return result

    # --- Pedidos ---------------------------------------------------------

    def _pedidos(self, user: UserModel) -> list[dict]:
        pedidos = self.db.scalars(
            select(OrderModel)
            .where(*self._scope(OrderModel, user, "commerce.read"))
            .order_by(OrderModel.created_at.desc())
            .limit(VENTANA)
        ).all()
        salida = []
        for pedido in pedidos:
            events = list(pedido.tracking or [])
            if pedido.payment_status == 'paid' and pedido.paid_at and not any(e.get('status') == 'paid' for e in events):
                events.append({'status': 'paid', 'date': pedido.paid_at})
            for indice, evento in enumerate(events):
                estado = evento.get("status", pedido.status)
                titulo, _distintivo, explicacion, _tono = ESTADOS_PEDIDO.get(
                    estado, ("Actualizamos tu pedido", "", "El pedido cambió de estado.", "")
                )
                salida.append(_aviso(
                    # El índice distingue dos eventos del mismo pedido y estado.
                    clave=f"order:{pedido.id}:{indice}",
                    tipo="pedido",
                    estado=estado,
                    titulo=titulo,
                    detalle=(f'{pedido.total:.2f} {pedido.currency.upper()} · {explicacion}' if estado == 'paid' else evento.get("note") or explicacion),
                    fecha=evento.get("date") or pedido.created_at,
                    enlace=("/admin/pedidos" if "commerce.read" in self.permissions and not self.support else "/mi-cuenta/pedidos") + "?pedido=" + str(pedido.id),
                    referencia=pedido.number,
                    event_key=f'payment:{pedido.id}:paid' if estado == 'paid' else None,
                    importante=estado in {'paid', 'cancelled', 'expired', 'delivered'},
                    tono='success' if estado in {'paid', 'delivered'} else 'warning' if estado in {'cancelled', 'expired'} else 'info',
                ))
        return salida

    # --- Reservas --------------------------------------------------------

    def _reservas(self, user: UserModel) -> list[dict]:
        reservas = self.db.scalars(
            select(ReservationModel)
            .where(*self._scope(ReservationModel, user, "reservations.read"))
            .order_by(ReservationModel.created_at.desc())
            .limit(VENTANA)
        ).all()
        salida = []
        for reserva in reservas:
            codigo = str(reserva.id).replace("-", "")[:8].upper()
            for indice, evento in enumerate(reserva.tracking or []):
                estado = evento.get("status", reserva.status)
                titulo, _d, explicacion, _t = ESTADOS_RESERVA.get(
                    estado, ("Actualizamos tu reserva", "", "La reserva cambió de estado.", "")
                )
                salida.append(_aviso(
                    clave=f"reservation:{reserva.id}:{indice}",
                    tipo="reserva",
                    estado=estado,
                    titulo=titulo,
                    detalle=evento.get("note") or explicacion,
                    fecha=evento.get("date") or reserva.created_at,
                    enlace="/admin/reservas" if "reservations.read" in self.permissions and not self.support else "/mi-cuenta/reservas",
                    referencia=codigo,
                    importante=estado in {'confirmed', 'ready', 'cancelled', 'expired', 'converted'},
                    tono='warning' if estado in {'cancelled', 'expired'} else 'success',
                ))
        return salida

    # --- Devoluciones ----------------------------------------------------

    def _devoluciones(self, user: UserModel) -> list[dict]:
        devoluciones = self.db.scalars(
            select(OrderReturnModel)
            .where(*self._scope(OrderReturnModel, user, "commerce.read"))
            .order_by(OrderReturnModel.created_at.desc())
            .limit(VENTANA)
        ).all()
        if not devoluciones:
            return []
        numeros = {
            o.id: o.number
            for o in self.db.scalars(
                select(OrderModel).where(OrderModel.tenant_id == self.tenant_id, OrderModel.id.in_({d.order_id for d in devoluciones}))
            )
        }
        salida = []
        for devolucion in devoluciones:
            codigo = str(devolucion.id).replace("-", "")[:8].upper()
            referencia = numeros.get(devolucion.order_id) or codigo
            # Una devolución no guarda historial: se arma con los dos momentos
            # que sí tiene, el pedido y la resolución.
            exchange = devolucion.reason.startswith('[CAMBIO]') or any(item.get('replacement_variant_id') for item in (devolucion.items or []))
            solicitud, _d, explicacion, _t = ESTADOS_DEVOLUCION["requested"]
            if exchange:
                solicitud, explicacion = 'Cambio de prenda solicitado', 'Registramos tu solicitud de cambio. Revisaremos la recepción y la diferencia de precio.'
            link = '/admin/devoluciones' if 'commerce.read' in self.permissions and not self.support else '/mi-cuenta/pedidos?pedido=' + str(devolucion.order_id)
            salida.append(_aviso(
                clave=f"return:{devolucion.id}:requested",
                tipo="devolucion", estado="requested", titulo=solicitud,
                detalle=explicacion, fecha=devolucion.created_at,
                enlace=link, referencia=referencia,
            ))
            if devolucion.status != "requested" and devolucion.resolved_at:
                titulo, _d2, explica, _t2 = ESTADOS_DEVOLUCION.get(
                    devolucion.status,
                    ("Actualizamos tu devolución", "", "La devolución cambió de estado.", ""),
                )
                if exchange:
                    titulo = {'approved': 'Cambio aprobado', 'rejected': 'Cambio rechazado', 'completed': 'Cambio completado'}.get(devolucion.status, 'Cambio actualizado')
                    settlement = {'paid': 'pago confirmado', 'refunded': 'reembolso confirmado', 'pending_payment': 'pago pendiente', 'pending_refund': 'reembolso pendiente', 'not_required': 'sin diferencia por liquidar'}.get(devolucion.settlement_status, 'pendiente de verificar')
                    explica = f'Diferencia: {devolucion.difference_amount:.2f} {devolucion.currency}. Liquidación: {settlement}.'
                salida.append(_aviso(
                    clave=f"return:{devolucion.id}:{devolucion.status}",
                    tipo="devolucion", estado=devolucion.status, titulo=titulo,
                    detalle=devolucion.resolution_note or explica,
                    fecha=devolucion.resolved_at,
                    importante=True, tono='warning' if devolucion.status == 'rejected' else 'success',
                    enlace=link, referencia=referencia,
                ))
            if exchange and devolucion.settlement_status in {'paid', 'refunded'}:
                state = devolucion.settlement_status
                salida.append(_aviso(
                    clave=f'exchange:{devolucion.id}:{state}', tipo='devolucion', estado=state,
                    titulo='Pago de diferencia confirmado' if state == 'paid' else 'Reembolso del cambio confirmado',
                    detalle=f'{abs(devolucion.difference_amount):.2f} {devolucion.currency.upper()} · La liquidación quedó registrada. Consultá el detalle del cambio.',
                    fecha=devolucion.updated_at, enlace=link, referencia=referencia,
                    importante=True, tono='success',
                ))
        return salida
