"""Qué dice cada aviso, según lo que le pasó al cliente.

Son funciones puras: reciben datos simples y devuelven asunto, texto y HTML. El
contenido de un aviso es lo que la persona termina leyendo, así que conviene
poder verificarlo sin base de datos ni servidor de correo.

Cubre CU15 (notificar cambio de estado), RF11 (avisar la reserva a la sucursal)
y CU19 (devoluciones y reembolsos). El marco visual vive en `diseno.py`.
"""
from src.notificaciones.domain import diseno
from src.notificaciones.domain.diseno import Mensaje

#: Etapas por las que pasa un pedido, para dibujar el progreso en el correo.
ETAPAS_PEDIDO = [
    ("pending_payment", "Recibido"),
    ("paid", "Pagado"),
    ("processing", "Preparando"),
    ("shipped", "En camino"),
    ("delivered", "Entregado"),
]

#: Para cada estado: título, explicación y tono del distintivo.
ESTADOS_PEDIDO: dict[str, tuple[str, str, str, str]] = {
    "pending_payment": (
        "Recibimos tu pedido",
        "Pedido registrado",
        "Ya apartamos tus prendas. En cuanto se acredite el pago lo preparamos.",
        "espera",
    ),
    "paid": (
        "Confirmamos tu pago",
        "Pago acreditado",
        "El pago quedó registrado. Ahora preparamos tu pedido en la tienda.",
        "exito",
    ),
    "processing": (
        "Estamos preparando tu pedido",
        "En preparación",
        "Tus prendas se están alistando para salir.",
        "neutro",
    ),
    "shipped": (
        "Tu pedido salió en camino",
        "En camino",
        "El pedido ya está con el transportista y va hacia la dirección que nos diste.",
        "neutro",
    ),
    "delivered": (
        "Tu pedido fue entregado",
        "Entregado",
        "El pedido llegó a destino. ¡Gracias por comprar con nosotros!",
        "exito",
    ),
    "cancelled": (
        "Tu pedido fue cancelado",
        "Cancelado",
        "El pedido se canceló y las prendas volvieron al stock.",
        "alerta",
    ),
    "expired": (
        "Venció el plazo de pago",
        "Pago vencido",
        "No se registró el pago a tiempo, así que liberamos las prendas apartadas.",
        "alerta",
    ),
}

ESTADOS_RESERVA: dict[str, tuple[str, str, str, str]] = {
    "pending": (
        "Registramos tu reserva",
        "Reserva registrada",
        "Apartamos las prendas. La sucursal va a confirmarte la visita en breve.",
        "espera",
    ),
    "confirmed": (
        "La sucursal confirmó tu reserva",
        "Confirmada",
        "Te esperamos en el horario que elegiste.",
        "exito",
    ),
    "ready": (
        "Tus prendas están listas para probar",
        "Prendas listas",
        "Quedaron preparadas en el probador de la sucursal.",
        "exito",
    ),
    "attended": (
        "Gracias por tu visita",
        "Visita atendida",
        "Registramos que fuiste atendido en la sucursal.",
        "neutro",
    ),
    "cancelled": (
        "Tu reserva fue cancelada",
        "Cancelada",
        "Las prendas que teníamos apartadas volvieron al stock.",
        "alerta",
    ),
}

ESTADOS_DEVOLUCION: dict[str, tuple[str, str, str, str]] = {
    "requested": (
        "Recibimos tu solicitud de devolución",
        "En revisión",
        "La estamos revisando. Te avisamos apenas tengamos una respuesta.",
        "espera",
    ),
    "approved": (
        "Aprobamos tu devolución",
        "Aprobada",
        "Podés acercar las prendas a la sucursal. El reintegro se procesa cuando las recibamos.",
        "exito",
    ),
    "rejected": (
        "No pudimos aprobar tu devolución",
        "Rechazada",
        "Revisá el motivo que te dejamos acá abajo.",
        "alerta",
    ),
    "completed": (
        "Tu devolución quedó cerrada",
        "Reembolso procesado",
        "Recibimos las prendas y procesamos el reintegro del importe.",
        "exito",
    ),
}

MEDIOS_PAGO = {
    "cash": "Efectivo",
    "qr": "Pago con QR",
    "card": "Tarjeta en el local",
    "transfer": "Transferencia",
    "stripe": "Tarjeta en línea",
    "manual": "Pago coordinado",
}


def _lista_texto(items: list[dict] | None) -> str:
    """Detalle legible de las prendas para la versión en texto plano."""
    lineas = []
    for item in items or []:
        detalle = " / ".join(str(item[c]) for c in ("size", "color") if item.get(c))
        lineas.append(
            f"  - {item.get('name', 'Prenda')}"
            f"{f' ({detalle})' if detalle else ''} x{item.get('quantity', 1)}"
        )
    return "\n".join(lineas)


def _texto(titulo: str, explicacion: str, filas, items, extra: list[str]) -> str:
    partes = [titulo.upper(), "", explicacion, ""]
    partes += [f"{etiqueta}: {valor}" for etiqueta, valor in filas if valor]
    if items:
        partes += ["", "Prendas:", _lista_texto(items)]
    partes += [p for p in extra if p]
    partes.append("\n--\nAviso automático de FashionStore. No respondas a este correo.")
    return "\n".join(partes)


# --- Pedidos --------------------------------------------------------------


def pedido_estado(
    *,
    numero: str,
    estado: str,
    items: list[dict] | None = None,
    total: str | None = None,
    moneda: str = "BOB",
    transportista: str | None = None,
    seguimiento: str | None = None,
    nota: str | None = None,
    enlace: str | None = None,
    metodo_pago: str | None = None,
    referencia: str | None = None,
) -> Mensaje:
    """Aviso de creación o de cambio de estado de un pedido (CU15)."""
    titulo, distintivo, explicacion, tono = ESTADOS_PEDIDO.get(
        estado, ("Actualizamos tu pedido", "Actualizado", "El pedido cambió de estado.", "neutro")
    )
    filas: list[tuple[str, str]] = [("Pedido", numero)]
    if metodo_pago:
        filas.append(("Forma de pago", MEDIOS_PAGO.get(metodo_pago, metodo_pago)))
    if referencia and estado in {"paid", "delivered"}:
        filas.append(("Referencia de pago", referencia))
    if estado == "shipped":
        if transportista:
            filas.append(("Transportista", transportista))
        if seguimiento:
            filas.append(("N.º de seguimiento", seguimiento))

    # Un pedido cancelado o vencido no muestra progreso: ya no avanza.
    alcanzadas = {"pending_payment", "paid", "processing", "shipped", "delivered"}
    corte = [clave for clave, _ in ETAPAS_PEDIDO]
    progreso = ""
    if estado in alcanzadas:
        limite = corte.index(estado)
        progreso = diseno.pasos([(nombre, i <= limite) for i, (_, nombre) in enumerate(ETAPAS_PEDIDO)])

    cuerpo = progreso + diseno.datos(filas) + diseno.prendas(items or [], moneda)
    if total:
        cuerpo += diseno.total("Total del pedido", total, moneda)
    if nota:
        cuerpo += diseno.nota(nota)
    if enlace:
        cuerpo += diseno.boton("Seguir mi pedido", enlace)

    return Mensaje(
        asunto=f"{titulo} · Pedido {numero}",
        texto=_texto(
            titulo, explicacion, filas, items,
            [f"\nTotal: {total} {moneda}" if total else "", f"\n{nota}" if nota else "",
             f"\nSeguí tu pedido acá: {enlace}" if enlace else ""],
        ),
        html=diseno.envolver(
            titulo=titulo, distintivo=distintivo, tono=tono, entrada=explicacion, contenido=cuerpo
        ),
    )


def comprobante_venta(
    *,
    numero: str,
    items: list[dict],
    total: str,
    moneda: str = "BOB",
    metodo_pago: str = "cash",
    referencia: str | None = None,
    sucursal: str | None = None,
    fecha: str | None = None,
    cliente: str | None = None,
) -> Mensaje:
    """Comprobante de una venta cobrada en caja (RF17, RF18).

    El cliente se lleva la prenda en el momento, así que el correo no informa un
    estado: **es el comprobante**. Lleva el detalle y la referencia del cobro
    para que sirva de respaldo.
    """
    titulo = "Comprobante de tu compra"
    filas = [
        ("Comprobante", numero),
        ("Cliente", cliente or "Consumidor final"),
        ("Sucursal", sucursal or ""),
        ("Fecha", fecha or ""),
        ("Forma de pago", MEDIOS_PAGO.get(metodo_pago, metodo_pago)),
        ("Referencia", referencia or ""),
    ]
    cuerpo = (
        diseno.datos(filas)
        + diseno.prendas(items, moneda)
        + diseno.total("Total cobrado", total, moneda)
        + diseno.nota(
            "Guardá este comprobante: es lo que necesitás para cambiar o devolver "
            "una prenda dentro de los 15 días."
        )
    )
    explicacion = "Gracias por tu compra. Acá está el detalle de lo que llevaste."
    return Mensaje(
        asunto=f"{titulo} · {numero}",
        texto=_texto(titulo, explicacion, filas, items, [f"\nTotal cobrado: {total} {moneda}"]),
        html=diseno.envolver(
            titulo=titulo, distintivo="Venta cobrada", tono="exito",
            entrada=explicacion, contenido=cuerpo,
        ),
    )


def pedido_para_sucursal(
    *,
    numero: str,
    sucursal: str,
    cliente: str,
    contacto: str | None = None,
    items: list[dict] | None = None,
    total: str | None = None,
    moneda: str = "BOB",
    metodo_pago: str | None = None,
    direccion: str | None = None,
    enlace: str | None = None,
) -> Mensaje:
    """Aviso interno: la sucursal tiene un pedido web por preparar.

    Sin esto, un pedido solo se descubre si alguien mira el panel. Las prendas
    ya quedaron apartadas del stock, así que la demora en verlo es demora real
    para el cliente.
    """
    titulo = f"Nuevo pedido por preparar en {sucursal}"
    explicacion = "Entró un pedido web. Las prendas ya están apartadas del stock de la sucursal."
    filas = [
        ("Pedido", numero),
        ("Cliente", cliente),
        ("Contacto", contacto or ""),
        ("Forma de pago", MEDIOS_PAGO.get(metodo_pago or "", metodo_pago or "")),
        ("Entrega", direccion or ""),
    ]
    cuerpo = diseno.datos(filas) + diseno.prendas(items or [], moneda)
    if total:
        cuerpo += diseno.total("Total del pedido", total, moneda)
    cuerpo += diseno.nota(
        "Preparen las prendas y actualicen el estado del pedido en el panel para que el "
        "cliente vea el avance."
    )
    if enlace:
        cuerpo += diseno.boton("Ver el pedido", enlace)
    return Mensaje(
        asunto=f"Nuevo pedido {numero} · {sucursal}",
        texto=_texto(titulo, explicacion, filas, items,
                     [f"\nTotal: {total} {moneda}" if total else "",
                      f"\nGestionalo acá: {enlace}" if enlace else ""]),
        html=diseno.envolver(titulo=titulo, distintivo="Por preparar", tono="espera",
                             entrada=explicacion, contenido=cuerpo),
    )


def devolucion_para_gestion(
    *,
    codigo: str,
    numero_pedido: str,
    sucursal: str,
    cliente: str,
    motivo: str,
    items: list[dict] | None = None,
    monto: str | None = None,
    moneda: str = "BOB",
    enlace: str | None = None,
) -> Mensaje:
    """Aviso interno: hay una devolución esperando resolución (CU19).

    Una solicitud sin revisar es un cliente esperando y unas unidades que no se
    pueden vender ni dar por perdidas.
    """
    titulo = "Nueva devolución por revisar"
    explicacion = f"Un cliente pidió devolver prendas del pedido {numero_pedido}."
    filas = [
        ("Devolución", codigo),
        ("Pedido", numero_pedido),
        ("Cliente", cliente),
        ("Sucursal", sucursal),
    ]
    cuerpo = diseno.datos(filas) + diseno.prendas(items or [], moneda)
    if monto:
        cuerpo += diseno.total("Importe a reintegrar", monto, moneda)
    cuerpo += diseno.nota(f"Motivo del cliente: {motivo}")
    if enlace:
        cuerpo += diseno.boton("Resolver la devolución", enlace)
    return Mensaje(
        asunto=f"Devolución {codigo} por revisar · Pedido {numero_pedido}",
        texto=_texto(titulo, explicacion, filas, items,
                     [f"\nImporte: {monto} {moneda}" if monto else "",
                      f"\nMotivo: {motivo}", f"\nResolvela acá: {enlace}" if enlace else ""]),
        html=diseno.envolver(titulo=titulo, distintivo="Por revisar", tono="espera",
                             entrada=explicacion, contenido=cuerpo),
    )


# --- Reservas -------------------------------------------------------------


def reserva_estado(
    *,
    codigo: str,
    estado: str,
    sucursal: str,
    direccion: str | None = None,
    fecha: str | None = None,
    items: list[dict] | None = None,
    nota: str | None = None,
    enlace: str | None = None,
) -> Mensaje:
    """Aviso al cliente sobre su reserva de probador (CU15)."""
    titulo, distintivo, explicacion, tono = ESTADOS_RESERVA.get(
        estado, ("Actualizamos tu reserva", "Actualizada", "La reserva cambió de estado.", "neutro")
    )
    filas = [
        ("Reserva", codigo),
        ("Sucursal", sucursal),
        ("Dirección", direccion or ""),
        ("Fecha y hora", fecha or ""),
    ]
    cuerpo = diseno.datos(filas) + diseno.prendas(items or [])
    if nota:
        cuerpo += diseno.nota(nota)
    if estado in {"confirmed", "ready"}:
        cuerpo += diseno.nota(
            "Llegá unos minutos antes y mostrá este correo en el mostrador. "
            "Si no vas a poder venir, cancelá la reserva para liberar las prendas."
        )
    if enlace:
        cuerpo += diseno.boton("Ver mi reserva", enlace)

    return Mensaje(
        asunto=f"{titulo} · Reserva {codigo}",
        texto=_texto(
            titulo, explicacion, filas, items,
            [f"\n{nota}" if nota else "", f"\nRevisá tu reserva acá: {enlace}" if enlace else ""],
        ),
        html=diseno.envolver(
            titulo=titulo, distintivo=distintivo, tono=tono, entrada=explicacion, contenido=cuerpo
        ),
    )


def reserva_para_sucursal(
    *,
    codigo: str,
    sucursal: str,
    cliente: str,
    contacto: str | None = None,
    fecha: str | None = None,
    items: list[dict] | None = None,
    notas: str | None = None,
    enlace: str | None = None,
) -> Mensaje:
    """Aviso a la sucursal de que tiene una reserva por atender (RF11)."""
    titulo = f"Nueva reserva por atender en {sucursal}"
    explicacion = "Un cliente agendó una visita para probarse estas prendas."
    filas = [
        ("Reserva", codigo),
        ("Cliente", cliente),
        ("Contacto", contacto or ""),
        ("Fecha y hora", fecha or ""),
    ]
    cuerpo = diseno.datos(filas) + diseno.prendas(items or [], importes=False)
    if notas:
        cuerpo += diseno.nota(f"Comentario del cliente: {notas}")
    cuerpo += diseno.nota("Preparen las prendas antes del horario y confirmen la reserva en el panel.")
    if enlace:
        cuerpo += diseno.boton("Gestionar la reserva", enlace)

    return Mensaje(
        asunto=f"Nueva reserva {codigo} · {sucursal}",
        texto=_texto(
            titulo, explicacion, filas, items,
            [f"\nComentario del cliente: {notas}" if notas else "",
             f"\nGestionala acá: {enlace}" if enlace else ""],
        ),
        html=diseno.envolver(
            titulo=titulo, distintivo="Por atender", tono="espera",
            entrada=explicacion, contenido=cuerpo,
        ),
    )


# --- Devoluciones y reembolsos --------------------------------------------


def devolucion_estado(
    *,
    codigo: str,
    numero_pedido: str,
    estado: str,
    items: list[dict] | None = None,
    monto: str | None = None,
    moneda: str = "BOB",
    nota: str | None = None,
    enlace: str | None = None,
    metodo_reembolso: str | None = None,
) -> Mensaje:
    """Aviso al cliente sobre su devolución y su reembolso (CU19)."""
    titulo, distintivo, explicacion, tono = ESTADOS_DEVOLUCION.get(
        estado,
        ("Actualizamos tu devolución", "Actualizada", "La devolución cambió de estado.", "neutro"),
    )
    filas = [("Devolución", codigo), ("Pedido", numero_pedido)]
    if estado == "completed" and metodo_reembolso:
        filas.append(("Reembolso por", MEDIOS_PAGO.get(metodo_reembolso, metodo_reembolso)))

    cuerpo = diseno.datos(filas) + diseno.prendas(items or [], moneda)
    if monto:
        etiqueta = "Importe reembolsado" if estado == "completed" else "Importe a reintegrar"
        cuerpo += diseno.total(etiqueta, monto, moneda)
    if nota:
        cuerpo += diseno.nota(nota)
    if estado == "approved":
        cuerpo += diseno.nota(
            "Llevá las prendas a la sucursal con este correo. El reintegro se procesa "
            "cuando las recibimos y verificamos su estado."
        )
    if enlace:
        cuerpo += diseno.boton("Ver mi devolución", enlace)

    return Mensaje(
        asunto=f"{titulo} · Pedido {numero_pedido}",
        texto=_texto(
            titulo, explicacion, filas, items,
            [f"\nImporte: {monto} {moneda}" if monto else "", f"\n{nota}" if nota else "",
             f"\nSeguí tu devolución acá: {enlace}" if enlace else ""],
        ),
        html=diseno.envolver(
            titulo=titulo, distintivo=distintivo, tono=tono, entrada=explicacion, contenido=cuerpo
        ),
    )
