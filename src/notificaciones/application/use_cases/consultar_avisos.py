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


def _aviso(*, clave, tipo, estado, titulo, detalle, fecha, enlace, referencia) -> dict:
    return {
        "id": clave,
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

    def execute(self, user: UserModel, limit: int = 20) -> list[dict]:
        avisos = self._pedidos(user) + self._reservas(user) + self._devoluciones(user)
        avisos.sort(key=lambda a: a["fecha"], reverse=True)
        return avisos[:limit]

    # --- Pedidos ---------------------------------------------------------

    def _pedidos(self, user: UserModel) -> list[dict]:
        pedidos = self.db.scalars(
            select(OrderModel)
            .where(OrderModel.user_id == user.id)
            .order_by(OrderModel.created_at.desc())
            .limit(VENTANA)
        ).all()
        salida = []
        for pedido in pedidos:
            for indice, evento in enumerate(pedido.tracking or []):
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
                    detalle=evento.get("note") or explicacion,
                    fecha=evento.get("date") or pedido.created_at,
                    enlace="/mi-cuenta/pedidos",
                    referencia=pedido.number,
                ))
        return salida

    # --- Reservas --------------------------------------------------------

    def _reservas(self, user: UserModel) -> list[dict]:
        reservas = self.db.scalars(
            select(ReservationModel)
            .where(ReservationModel.user_id == user.id)
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
                    enlace="/mi-cuenta/reservas",
                    referencia=codigo,
                ))
        return salida

    # --- Devoluciones ----------------------------------------------------

    def _devoluciones(self, user: UserModel) -> list[dict]:
        devoluciones = self.db.scalars(
            select(OrderReturnModel)
            .where(OrderReturnModel.user_id == user.id)
            .order_by(OrderReturnModel.created_at.desc())
            .limit(VENTANA)
        ).all()
        if not devoluciones:
            return []
        numeros = {
            o.id: o.number
            for o in self.db.scalars(
                select(OrderModel).where(OrderModel.id.in_({d.order_id for d in devoluciones}))
            )
        }
        salida = []
        for devolucion in devoluciones:
            codigo = str(devolucion.id).replace("-", "")[:8].upper()
            referencia = numeros.get(devolucion.order_id) or codigo
            # Una devolución no guarda historial: se arma con los dos momentos
            # que sí tiene, el pedido y la resolución.
            solicitud, _d, explicacion, _t = ESTADOS_DEVOLUCION["requested"]
            salida.append(_aviso(
                clave=f"return:{devolucion.id}:requested",
                tipo="devolucion", estado="requested", titulo=solicitud,
                detalle=explicacion, fecha=devolucion.created_at,
                enlace="/mi-cuenta/pedidos", referencia=referencia,
            ))
            if devolucion.status != "requested" and devolucion.resolved_at:
                titulo, _d2, explica, _t2 = ESTADOS_DEVOLUCION.get(
                    devolucion.status,
                    ("Actualizamos tu devolución", "", "La devolución cambió de estado.", ""),
                )
                salida.append(_aviso(
                    clave=f"return:{devolucion.id}:{devolucion.status}",
                    tipo="devolucion", estado=devolucion.status, titulo=titulo,
                    detalle=devolucion.resolution_note or explica,
                    fecha=devolucion.resolved_at,
                    enlace="/mi-cuenta/pedidos", referencia=referencia,
                ))
        return salida
