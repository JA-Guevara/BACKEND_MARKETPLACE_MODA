"""Avisos de negocio: qué se notifica, a quién y con qué texto.

Es el punto único donde compras y reservas piden "avisá de esto". Los casos de
uso de negocio no arman correos ni saben de SMTP: llaman a un método con el
pedido o la reserva ya guardados.

Cubre CU15 (notificar cambio de estado) y RF11 (avisar la reserva a la sucursal).
"""
import uuid
from datetime import timezone, timedelta

from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.config.settings import settings
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.notificaciones.application.use_cases.send_email import EnviarCorreo
from src.notificaciones.domain import plantillas

#: Bolivia no cambia de horario; mostrar UTC confundiría la hora de la cita.
HUSO_LOCAL = timezone(timedelta(hours=-4))


def _codigo(identificador) -> str:
    """Código corto y legible para nombrar una reserva en un correo."""
    return str(identificador).replace("-", "")[:8].upper()


def _fecha(valor) -> str | None:
    if not valor:
        return None
    momento = valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    return momento.astimezone(HUSO_LOCAL).strftime("%d/%m/%Y %H:%M")


class ServicioNotificaciones:
    """Avisos por correo de pedidos y reservas.

    Todos los métodos son "lo mejor posible": devuelven si el correo salió, pero
    no interrumpen la operación que los llamó.
    """

    def __init__(self, db: Session, correo: EnviarCorreo | None = None) -> None:
        self.db = db
        self.correo = correo or EnviarCorreo(db)

    # --- Pedidos ---------------------------------------------------------

    def pedido(self, order, nota: str | None = None) -> bool:
        """Avisa al cliente el estado en que quedó su pedido.

        Una venta de caja no informa un estado —el cliente ya se llevó la
        prenda—, así que recibe el comprobante de la compra.
        """
        if order.sales_channel == "pos":
            return self.comprobante(order)
        mensaje = plantillas.pedido_estado(
            numero=order.number,
            estado=order.status,
            items=order.items,
            total=f"{order.total}",
            moneda=order.currency,
            transportista=order.carrier,
            seguimiento=order.tracking_number,
            nota=nota,
            enlace=f"{settings.frontend_url}/mi-cuenta/pedidos",
            metodo_pago=order.payment_method,
            referencia=order.payment_reference,
        )
        return self.correo.execute(
            destinatario=order.customer_email,
            mensaje=mensaje,
            entidad="order",
            entidad_id=str(order.id),
            actor_id=order.user_id,
            contexto={"number": order.number, "status": order.status},
        )

    def comprobante(self, order) -> bool:
        """RF17/RF18: el comprobante de una venta cobrada en caja, al correo del cliente."""
        sucursal = self._sucursal(order.branch_id)
        mensaje = plantillas.comprobante_venta(
            numero=order.number,
            items=order.items,
            total=f"{order.total}",
            moneda=order.currency,
            metodo_pago=order.payment_method,
            referencia=order.payment_reference,
            sucursal=sucursal.name if sucursal else None,
            fecha=_fecha(order.paid_at or order.created_at),
            cliente=(order.address or {}).get("recipient"),
        )
        return self.correo.execute(
            destinatario=order.customer_email,
            mensaje=mensaje,
            entidad="order",
            entidad_id=str(order.id),
            actor_id=order.user_id,
            contexto={"number": order.number, "canal": "pos"},
        )

    def devolucion(self, devolucion, order, nota: str | None = None) -> bool:
        """CU19: el cliente sigue su devolución desde que la pide hasta el cierre."""
        mensaje = plantillas.devolucion_estado(
            codigo=_codigo(devolucion.id),
            numero_pedido=order.number,
            estado=devolucion.status,
            items=devolucion.items,
            monto=f"{devolucion.refund_amount}",
            moneda=devolucion.currency,
            nota=nota or devolucion.resolution_note,
            enlace=f"{settings.frontend_url}/mi-cuenta/pedidos",
            metodo_reembolso=order.payment_method,
        )
        return self.correo.execute(
            destinatario=order.customer_email,
            mensaje=mensaje,
            entidad="order_return",
            entidad_id=str(devolucion.id),
            actor_id=devolucion.user_id,
            contexto={"number": order.number, "status": devolucion.status},
        )

    # --- Avisos internos -------------------------------------------------

    def _casilla_sucursal(self, branch) -> str | None:
        """A dónde va un aviso interno de esa sucursal."""
        return (branch.notification_email if branch else None) or settings.operations_email

    def pedido_a_sucursal(self, order) -> bool:
        """Avisa a la sucursal que tiene un pedido web por preparar.

        Sin este aviso el pedido solo se descubre mirando el panel, mientras las
        prendas ya quedaron apartadas del stock.
        """
        sucursal = self._sucursal(order.branch_id)
        direccion = order.address or {}
        partes = [direccion.get("line1"), direccion.get("city"), direccion.get("country")]
        mensaje = plantillas.pedido_para_sucursal(
            numero=order.number,
            sucursal=sucursal.name if sucursal else "Sucursal",
            cliente=direccion.get("recipient") or order.customer_email,
            contacto=" · ".join(filter(None, [direccion.get("phone"), order.customer_email])),
            items=order.items,
            total=f"{order.total}",
            moneda=order.currency,
            metodo_pago=order.payment_method,
            direccion=", ".join(p for p in partes if p),
            enlace=f"{settings.frontend_url}/admin/pedidos?pedido={order.id}",
        )
        return self.correo.execute(
            destinatario=self._casilla_sucursal(sucursal),
            mensaje=mensaje,
            entidad="order",
            entidad_id=str(order.id),
            actor_id=order.user_id,
            contexto={"destino": "sucursal", "number": order.number},
        )

    def devolucion_a_gestion(self, devolucion, order) -> bool:
        """Avisa que hay una devolución esperando resolución (CU19)."""
        sucursal = self._sucursal(devolucion.branch_id)
        mensaje = plantillas.devolucion_para_gestion(
            codigo=_codigo(devolucion.id),
            numero_pedido=order.number,
            sucursal=sucursal.name if sucursal else "Sucursal",
            cliente=(order.address or {}).get("recipient") or order.customer_email,
            motivo=devolucion.reason,
            items=devolucion.items,
            monto=f"{devolucion.refund_amount}",
            moneda=devolucion.currency,
            enlace=f"{settings.frontend_url}/admin/devoluciones",
        )
        return self.correo.execute(
            destinatario=self._casilla_sucursal(sucursal),
            mensaje=mensaje,
            entidad="order_return",
            entidad_id=str(devolucion.id),
            actor_id=devolucion.user_id,
            contexto={"destino": "gestion", "number": order.number},
        )

    # --- Reservas --------------------------------------------------------

    def _sucursal(self, branch_id) -> BranchModel | None:
        return self.db.get(BranchModel, branch_id)

    def reserva(self, reserva, nota: str | None = None) -> bool:
        """Avisa al cliente el estado en que quedó su reserva."""
        sucursal = self._sucursal(reserva.branch_id)
        cliente = self.db.get(UserModel, reserva.user_id)
        mensaje = plantillas.reserva_estado(
            codigo=_codigo(reserva.id),
            estado=reserva.status,
            sucursal=sucursal.name if sucursal else "Sucursal",
            direccion=sucursal.address if sucursal else None,
            fecha=_fecha(reserva.scheduled_at),
            items=reserva.items,
            nota=nota,
            enlace=f"{settings.frontend_url}/mi-cuenta/reservas",
        )
        return self.correo.execute(
            destinatario=cliente.email if cliente else None,
            mensaje=mensaje,
            entidad="reservation",
            entidad_id=str(reserva.id),
            actor_id=reserva.user_id,
            contexto={"status": reserva.status},
        )

    def reserva_a_sucursal(self, reserva) -> bool:
        """RF11: la sucursal se entera de que tiene prendas que preparar.

        Si la sucursal no tiene correo cargado se usa la casilla de operaciones,
        para que el aviso no se pierda mientras se completan los datos.
        """
        sucursal = self._sucursal(reserva.branch_id)
        cliente = self.db.get(UserModel, reserva.user_id)
        destinatario = self._casilla_sucursal(sucursal)
        mensaje = plantillas.reserva_para_sucursal(
            codigo=_codigo(reserva.id),
            sucursal=sucursal.name if sucursal else "Sucursal",
            cliente=f"{cliente.first_name} {cliente.last_name}".strip() if cliente else "Cliente",
            # La sucursal necesita poder llamar al cliente si algo cambia.
            contacto=" · ".join(filter(None, [cliente.phone, cliente.email])) if cliente else None,
            fecha=_fecha(reserva.scheduled_at),
            items=reserva.items,
            notas=reserva.notes,
            enlace=f"{settings.frontend_url}/admin/reservas",
        )
        return self.correo.execute(
            destinatario=destinatario,
            mensaje=mensaje,
            entidad="reservation",
            entidad_id=str(reserva.id),
            actor_id=reserva.user_id,
            contexto={"destino": "sucursal", "branch_id": str(reserva.branch_id)},
        )


def notificar_pedido(
    db: Session, order, nota: str | None = None, avisar_sucursal: bool = False
) -> None:
    """Atajo tolerante a fallos para llamar desde un caso de uso ya confirmado."""
    try:
        servicio = ServicioNotificaciones(db)
        servicio.pedido(order, nota)
        if avisar_sucursal:
            servicio.pedido_a_sucursal(order)
    except Exception:  # noqa: BLE001 - el aviso nunca revierte la venta
        pass


def notificar_devolucion(
    db: Session, devolucion, order, nota: str | None = None, avisar_gestion: bool = False
) -> None:
    try:
        servicio = ServicioNotificaciones(db)
        servicio.devolucion(devolucion, order, nota)
        if avisar_gestion:
            servicio.devolucion_a_gestion(devolucion, order)
    except Exception:  # noqa: BLE001
        pass


def notificar_reserva(db: Session, reserva, nota: str | None = None, avisar_sucursal: bool = False) -> None:
    try:
        servicio = ServicioNotificaciones(db)
        servicio.reserva(reserva, nota)
        if avisar_sucursal:
            servicio.reserva_a_sucursal(reserva)
    except Exception:  # noqa: BLE001
        pass
