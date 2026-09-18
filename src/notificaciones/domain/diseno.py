"""Armado del correo: la misma pieza visual para todos los avisos.

Un correo no es una página web. Gmail, Outlook y los clientes de escritorio
recortan el CSS moderno, ignoran las hojas externas y algunos borran hasta el
bloque `<style>`. Por eso acá todo se dibuja con **tablas y estilos en línea**,
que es lo único que se ve igual en todos lados, y el ancho se fija en 600px,
que es el que entra sin scroll horizontal en un teléfono.

Cada aviso arma su contenido con estos bloques y `envolver()` le pone el marco.
Así hay un solo lugar donde cambiar la identidad visual.
"""
from dataclasses import dataclass
from html import escape

# Los mismos colores que la web (`styles.scss`), para que el correo no parezca
# de otra tienda.
ACENTO = "#74394e"
TINTA = "#24231f"
PAPEL = "#faf9f6"
LINEA = "#e5e2da"
SUAVE = "#736c65"

#: Color del distintivo segun como le vaya al cliente en esa etapa.
TONOS = {
    "neutro": ("#eef1f4", "#33404d"),
    "exito": ("#e8f3ec", "#1f5c3a"),
    "espera": ("#fdf3e3", "#7a5310"),
    "alerta": ("#fbeaea", "#8f2d2d"),
}


@dataclass(frozen=True)
class Mensaje:
    """Correo listo para enviar, en sus dos versiones.

    `texto` no es un descarte: es lo que leen los clientes que bloquean HTML y
    lo que evita que el correo caiga en spam por tener solo una parte.
    """

    asunto: str
    texto: str
    html: str


def _fila_detalle(etiqueta: str, valor: str) -> str:
    return (
        f'<tr><td style="padding:4px 0;color:{SUAVE};font-size:13px">{escape(etiqueta)}</td>'
        f'<td style="padding:4px 0;text-align:right;font-size:13px;color:{TINTA}">'
        f"<strong>{escape(valor)}</strong></td></tr>"
    )


def datos(filas: list[tuple[str, str]]) -> str:
    """Bloque de pares etiqueta/valor, como los datos de un pedido."""
    if not filas:
        return ""
    cuerpo = "".join(_fila_detalle(e, v) for e, v in filas if v)
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:0 0 20px;border-collapse:collapse">{cuerpo}</table>'
    )


def prendas(items: list[dict], moneda: str = "", importes: bool = True) -> str:
    """Tabla de prendas con talla, color y cantidad.

    `importes=False` la deja sin precios: el aviso a la sucursal sirve para
    preparar prendas, no para cobrar.
    """
    if not items:
        return ""
    filas = []
    for item in items:
        detalle = " · ".join(str(item[c]) for c in ("size", "color") if item.get(c))
        importe = item.get("line_total") if importes else None
        filas.append(
            f'<tr><td style="padding:10px 0;border-bottom:1px solid {LINEA}">'
            f'<div style="font-size:14px;color:{TINTA}"><strong>{escape(str(item.get("name", "Prenda")))}</strong></div>'
            f'<div style="font-size:12px;color:{SUAVE}">{escape(detalle)}'
            f'{" · " if detalle else ""}Cantidad: {int(item.get("quantity", 1))}</div></td>'
            f'<td style="padding:10px 0;border-bottom:1px solid {LINEA};text-align:right;'
            f'font-size:14px;color:{TINTA};white-space:nowrap">'
            f'{escape(f"{importe} {moneda}".strip()) if importe else ""}</td></tr>'
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:0 0 8px;border-collapse:collapse">{"".join(filas)}</table>'
    )


def total(etiqueta: str, importe: str, moneda: str) -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:0 0 24px;border-collapse:collapse"><tr>'
        f'<td style="padding:12px 0;font-size:15px;color:{TINTA}">{escape(etiqueta)}</td>'
        f'<td style="padding:12px 0;text-align:right;font-size:18px;color:{ACENTO}">'
        f"<strong>{escape(importe)} {escape(moneda)}</strong></td></tr></table>"
    )


def nota(texto: str) -> str:
    """Comentario destacado: el motivo de un rechazo, una instrucción."""
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:0 0 24px;border-collapse:collapse"><tr><td '
        f'style="padding:14px 16px;background:{PAPEL};border-left:3px solid {ACENTO};'
        f'font-size:14px;line-height:1.5;color:{TINTA}">{escape(texto)}</td></tr></table>'
    )


def boton(texto: str, enlace: str) -> str:
    """Llamado a la acción. Va como tabla porque Outlook rompe los `<a>` con padding."""
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="margin:0 0 8px;border-collapse:separate"><tr>'
        f'<td style="border-radius:8px;background:{ACENTO}">'
        f'<a href="{escape(enlace, quote=True)}" style="display:inline-block;padding:12px 26px;'
        f'font-family:Helvetica,Arial,sans-serif;font-size:14px;color:#ffffff;'
        f'text-decoration:none;border-radius:8px">{escape(texto)}</a></td></tr></table>'
    )


def pasos(etapas: list[tuple[str, bool]]) -> str:
    """Línea de progreso del pedido: cada etapa cumplida se marca.

    Es la misma idea que la línea de tiempo de «Mis pedidos», reducida a lo que
    un correo puede dibujar sin romperse.
    """
    if not etapas:
        return ""
    celdas = []
    for nombre, hecha in etapas:
        color = ACENTO if hecha else LINEA
        texto = TINTA if hecha else SUAVE
        celdas.append(
            f'<td align="center" style="padding:0 2px">'
            f'<div style="height:4px;background:{color};border-radius:2px;margin-bottom:6px"></div>'
            f'<div style="font-size:10px;color:{texto};line-height:1.3">{escape(nombre)}</div></td>'
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:0 0 24px;border-collapse:collapse"><tr>{"".join(celdas)}</tr></table>'
    )


def envolver(*, titulo: str, distintivo: str, tono: str, entrada: str, contenido: str) -> str:
    """Marco del correo: encabezado, cuerpo y pie."""
    fondo_dist, texto_dist = TONOS.get(tono, TONOS["neutro"])
    return f"""\
<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(titulo)}</title></head>
<body style="margin:0;padding:0;background:{PAPEL};">
<!-- Resumen que algunos clientes muestran junto al asunto en la bandeja. -->
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{escape(entrada)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:{PAPEL};border-collapse:collapse">
<tr><td align="center" style="padding:28px 12px">
<table role="presentation" width="600" cellpadding="0" cellspacing="0"
       style="width:100%;max-width:600px;border-collapse:collapse;background:#ffffff;
              border:1px solid {LINEA};border-radius:14px;overflow:hidden;
              font-family:Helvetica,Arial,sans-serif">
  <tr><td style="padding:22px 32px;background:{ACENTO}">
    <span style="font-size:17px;letter-spacing:2px;color:#ffffff;font-weight:bold">FASHIONSTORE</span>
  </td></tr>
  <tr><td style="padding:32px 32px 8px">
    <span style="display:inline-block;padding:5px 12px;border-radius:999px;
                 background:{fondo_dist};color:{texto_dist};font-size:11px;
                 letter-spacing:1px;text-transform:uppercase">{escape(distintivo)}</span>
    <h1 style="margin:16px 0 8px;font-size:23px;line-height:1.3;color:{TINTA}">{escape(titulo)}</h1>
    <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:{SUAVE}">{escape(entrada)}</p>
{contenido}
  </td></tr>
  <tr><td style="padding:20px 32px 28px;border-top:1px solid {LINEA}">
    <p style="margin:0;font-size:12px;line-height:1.6;color:{SUAVE}">
      Este es un aviso automático de FashionStore. No respondas a este correo:
      nadie lee esta casilla. Si necesitás ayuda, escribinos desde la tienda o
      acercate a tu sucursal.
    </p>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""
