"""Reglas de una devolución, sin base de datos ni HTTP (CU19).

Una devolución solo tiene sentido sobre un pedido entregado y pagado, dentro
del plazo, y por prendas que el cliente todavía no devolvió. Todo eso se decide
acá para poder verificarlo sin montar un pedido real.
"""
from datetime import datetime, timedelta, timezone

#: Plazo para pedir una devolución desde que el pedido se entregó.
DIAS_PARA_DEVOLVER = 15

#: A qué estado puede pasar una devolución desde el que tiene.
TRANSICIONES: dict[str, set[str]] = {
    "requested": {"approved", "rejected"},
    "approved": {"completed", "rejected"},
}

#: Estados que todavía comprometen unidades del pedido.
VIGENTES = {"requested", "approved", "completed"}


def _utc(valor: datetime) -> datetime:
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def fecha_de_entrega(order) -> datetime | None:
    """Cuándo se entregó, según el historial de seguimiento."""
    for evento in reversed(order.tracking or []):
        if evento.get("status") == "delivered" and evento.get("date"):
            try:
                return _utc(datetime.fromisoformat(evento["date"]))
            except ValueError:
                return None
    return None


def motivo_para_rechazar(order, ahora: datetime | None = None) -> str | None:
    """Por qué NO se puede devolver este pedido; None si sí se puede."""
    ahora = _utc(ahora or datetime.now(timezone.utc))
    if order.status != "delivered":
        return "Solo se pueden devolver pedidos ya entregados."
    if order.payment_status != "paid":
        return "El pedido no figura como pagado."
    entregado = fecha_de_entrega(order) or _utc(order.created_at)
    if ahora - entregado > timedelta(days=DIAS_PARA_DEVOLVER):
        return f"El plazo de {DIAS_PARA_DEVOLVER} días para devolver ya venció."
    return None


def unidades_comprometidas(devoluciones) -> dict[str, int]:
    """Unidades por variante que ya están en una devolución vigente."""
    comprometidas: dict[str, int] = {}
    for devolucion in devoluciones:
        if devolucion.status not in VIGENTES:
            continue
        for item in devolucion.items or []:
            clave = str(item["variant_id"])
            comprometidas[clave] = comprometidas.get(clave, 0) + int(item["quantity"])
    return comprometidas


def unidades_devolvibles(order, devoluciones) -> dict[str, int]:
    """Cuánto queda por devolver de cada variante del pedido."""
    comprometidas = unidades_comprometidas(devoluciones)
    disponibles: dict[str, int] = {}
    for item in order.items or []:
        clave = str(item["variant_id"])
        restante = int(item["quantity"]) - comprometidas.get(clave, 0)
        if restante > 0:
            disponibles[clave] = restante
    return disponibles


def armar_detalle(order, devoluciones, solicitados: list[tuple[str, int]]) -> list[dict]:
    """Copia de las prendas devueltas, con su precio, o explica qué no cierra.

    Se guarda una copia y no una referencia porque el catálogo puede cambiar de
    precio después; la devolución tiene que reflejar lo que se cobró.
    """
    if not solicitados:
        raise ValueError("Indicá al menos una prenda para devolver.")
    disponibles = unidades_devolvibles(order, devoluciones)
    por_variante = {str(item["variant_id"]): item for item in order.items or []}
    detalle: list[dict] = []
    agrupado: dict[str, int] = {}
    for variant_id, cantidad in solicitados:
        if cantidad < 1:
            raise ValueError("La cantidad a devolver debe ser al menos 1.")
        agrupado[str(variant_id)] = agrupado.get(str(variant_id), 0) + int(cantidad)
    for variant_id, cantidad in agrupado.items():
        item = por_variante.get(variant_id)
        if not item:
            raise ValueError("Una de las prendas no pertenece a este pedido.")
        disponible = disponibles.get(variant_id, 0)
        if cantidad > disponible:
            nombre = item.get("name", "una prenda")
            raise ValueError(
                f"De {nombre} quedan {disponible} unidades por devolver y pediste {cantidad}."
            )
        unitario = float(item.get("unit_price") or 0)
        detalle.append({
            "variant_id": variant_id,
            "name": item.get("name"),
            "sku": item.get("sku"),
            "size": item.get("size"),
            "color": item.get("color"),
            "quantity": cantidad,
            "unit_price": f"{unitario:.2f}",
            "line_total": f"{unitario * cantidad:.2f}",
        })
    return detalle


def monto(detalle: list[dict]) -> str:
    """Importe a reintegrar por las prendas devueltas."""
    return f"{sum(float(row['line_total']) for row in detalle):.2f}"
