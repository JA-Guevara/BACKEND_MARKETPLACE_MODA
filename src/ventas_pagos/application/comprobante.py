"""Comprobante de venta en PDF, con la misma identidad que el correo.

El cliente puede recibir el comprobante por correo y llevarse el impreso: si los
dos no se parecen, parecen de tiendas distintas. Por eso los colores, el orden
de los datos y los textos salen de las mismas decisiones que
`src/notificaciones/domain/diseno.py`.

Se dibuja con ReportLab sobre A5, que es el tamaño que entra en una impresora de
mostrador sin desperdiciar papel.
"""
from io import BytesIO

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A5
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

from src.notificaciones.domain.plantillas import MEDIOS_PAGO

# Los mismos colores que la web y el correo.
ACENTO = HexColor("#74394e")
TINTA = HexColor("#24231f")
PAPEL = HexColor("#faf9f6")
LINEA = HexColor("#e5e2da")
SUAVE = HexColor("#736c65")
BLANCO = HexColor("#ffffff")

ANCHO, ALTO = A5
MARGEN = 34
#: Debajo de esta altura se corta la página: deja lugar al pie.
PISO = 70


def _texto(item: dict, clave: str, defecto: str = "") -> str:
    """Lee una clave del detalle sin romperse con pedidos viejos.

    El detalle de un pedido es una copia en JSON hecha en el momento de la
    venta. Los pedidos anteriores a un cambio de formato pueden no tener una
    clave, y un comprobante que no se puede reimprimir es un problema real en
    el mostrador.
    """
    valor = item.get(clave)
    return defecto if valor in (None, "") else str(valor)


class _Hoja:
    """Lleva la cuenta de dónde se está escribiendo y abre página cuando hace falta."""

    def __init__(self, pdf: canvas.Canvas) -> None:
        self.pdf = pdf
        self.y = 0.0

    def espacio(self, alto: float) -> None:
        if self.y - alto < PISO:
            self.pdf.showPage()
            self.encabezado_corto()

    def encabezado_corto(self) -> None:
        """Cabecera de las páginas siguientes: más chica, para no repetir el bloque."""
        self.pdf.setFillColor(ACENTO)
        self.pdf.rect(0, ALTO - 34, ANCHO, 34, stroke=0, fill=1)
        self.pdf.setFillColor(BLANCO)
        self.pdf.setFont("Helvetica-Bold", 10)
        self.pdf.drawString(MARGEN, ALTO - 22, "FASHIONSTORE")
        self.y = ALTO - 58


def _encabezado(hoja: _Hoja, distintivo: str, titulo: str, entrada: str) -> None:
    pdf = hoja.pdf
    pdf.setFillColor(ACENTO)
    pdf.rect(0, ALTO - 58, ANCHO, 58, stroke=0, fill=1)
    pdf.setFillColor(BLANCO)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(MARGEN, ALTO - 36, "FASHIONSTORE")

    y = ALTO - 88
    # Distintivo: una cápsula clara con el estado, igual que en el correo.
    pdf.setFont("Helvetica", 7.5)
    ancho_capsula = pdf.stringWidth(distintivo.upper(), "Helvetica", 7.5) + 16
    pdf.setFillColor(HexColor("#e8f3ec"))
    pdf.roundRect(MARGEN, y - 4, ancho_capsula, 15, 7, stroke=0, fill=1)
    pdf.setFillColor(HexColor("#1f5c3a"))
    pdf.drawString(MARGEN + 8, y, distintivo.upper())

    y -= 26
    pdf.setFillColor(TINTA)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(MARGEN, y, titulo)

    y -= 16
    pdf.setFillColor(SUAVE)
    pdf.setFont("Helvetica", 9)
    for renglon in simpleSplit(entrada, "Helvetica", 9, ANCHO - MARGEN * 2):
        pdf.drawString(MARGEN, y, renglon)
        y -= 12
    hoja.y = y - 10


def _datos(hoja: _Hoja, filas: list[tuple[str, str]]) -> None:
    pdf = hoja.pdf
    for etiqueta, valor in filas:
        if not valor:
            continue
        hoja.espacio(14)
        pdf.setFont("Helvetica", 8.5)
        pdf.setFillColor(SUAVE)
        pdf.drawString(MARGEN, hoja.y, etiqueta)
        pdf.setFont("Helvetica-Bold", 8.5)
        pdf.setFillColor(TINTA)
        pdf.drawRightString(ANCHO - MARGEN, hoja.y, valor)
        hoja.y -= 14
    hoja.y -= 8


def _prendas(hoja: _Hoja, items: list[dict], moneda: str) -> None:
    pdf = hoja.pdf
    for item in items:
        hoja.espacio(30)
        pdf.setFont("Helvetica-Bold", 9.5)
        pdf.setFillColor(TINTA)
        nombre = _texto(item, "name", "Prenda")
        pdf.drawString(MARGEN, hoja.y, nombre[:52])

        importe = _texto(item, "line_total")
        if importe:
            pdf.setFont("Helvetica", 9.5)
            pdf.drawRightString(ANCHO - MARGEN, hoja.y, f"{importe} {moneda}")

        detalle = " · ".join(
            p for p in (_texto(item, "size"), _texto(item, "color"), _texto(item, "sku")) if p
        )
        cantidad = item.get("quantity", 1)
        pdf.setFont("Helvetica", 7.5)
        pdf.setFillColor(SUAVE)
        pdf.drawString(MARGEN, hoja.y - 11, f"{detalle}{' · ' if detalle else ''}Cantidad: {cantidad}")

        pdf.setStrokeColor(LINEA)
        pdf.setLineWidth(0.6)
        pdf.line(MARGEN, hoja.y - 18, ANCHO - MARGEN, hoja.y - 18)
        hoja.y -= 30


def _total(hoja: _Hoja, etiqueta: str, importe: str, moneda: str) -> None:
    pdf = hoja.pdf
    hoja.espacio(34)
    hoja.y -= 6
    pdf.setFont("Helvetica", 10)
    pdf.setFillColor(TINTA)
    pdf.drawString(MARGEN, hoja.y, etiqueta)
    pdf.setFont("Helvetica-Bold", 14)
    pdf.setFillColor(ACENTO)
    pdf.drawRightString(ANCHO - MARGEN, hoja.y - 2, f"{importe} {moneda}")
    hoja.y -= 26


def _nota(hoja: _Hoja, texto: str) -> None:
    pdf = hoja.pdf
    renglones = simpleSplit(texto, "Helvetica", 8, ANCHO - MARGEN * 2 - 20)
    alto = len(renglones) * 11 + 14
    hoja.espacio(alto + 6)
    pdf.setFillColor(PAPEL)
    pdf.rect(MARGEN, hoja.y - alto + 10, ANCHO - MARGEN * 2, alto, stroke=0, fill=1)
    pdf.setFillColor(ACENTO)
    pdf.rect(MARGEN, hoja.y - alto + 10, 2.5, alto, stroke=0, fill=1)
    pdf.setFillColor(TINTA)
    pdf.setFont("Helvetica", 8)
    y = hoja.y
    for renglon in renglones:
        pdf.drawString(MARGEN + 12, y, renglon)
        y -= 11
    hoja.y = y - 14


def _pie(pdf: canvas.Canvas, numero: str) -> None:
    """Pie en todas las páginas, con el número para poder juntarlas."""
    total = pdf.getPageNumber()
    pdf.setStrokeColor(LINEA)
    pdf.setLineWidth(0.6)
    pdf.line(MARGEN, 52, ANCHO - MARGEN, 52)
    pdf.setFillColor(SUAVE)
    pdf.setFont("Helvetica", 7)
    pdf.drawString(MARGEN, 40, "FashionStore · Comprobante de venta")
    pdf.drawString(
        MARGEN,
        30,
        "Conservalo: es lo que necesitás para cambiar o devolver una prenda dentro de los 15 días.",
    )
    pdf.drawRightString(ANCHO - MARGEN, 40, f"{numero} · pág. {total}")


def comprobante_de_venta(order) -> BytesIO:
    """Arma el comprobante imprimible de una venta.

    Devuelve el PDF en memoria; el llamador decide si lo descarga o lo adjunta.
    """
    stream = BytesIO()
    pdf = canvas.Canvas(stream, pagesize=A5)
    pdf.setTitle(f"Comprobante {order.number}")
    pdf.setAuthor("FashionStore")

    hoja = _Hoja(pdf)
    presencial = order.sales_channel == "pos"
    _encabezado(
        hoja,
        "Venta cobrada" if presencial else "Pedido",
        "Comprobante de compra",
        "Gracias por tu compra. Acá está el detalle de lo que llevaste."
        if presencial
        else "Detalle de tu pedido.",
    )

    direccion = order.address or {}
    _datos(
        hoja,
        [
            ("Comprobante", order.number),
            ("Cliente", direccion.get("recipient") or order.customer_email or "Consumidor final"),
            ("Fecha", (order.paid_at or order.created_at).strftime("%d/%m/%Y %H:%M")),
            ("Forma de pago", MEDIOS_PAGO.get(order.payment_method, order.payment_method)),
            ("Referencia", order.payment_reference or ""),
        ],
    )
    _prendas(hoja, order.items or [], order.currency)
    _total(hoja, "Total cobrado" if presencial else "Total del pedido", f"{order.total}", order.currency)
    _nota(
        hoja,
        "Para un cambio o una devolución, acercate a la sucursal con este comprobante "
        "dentro de los 15 días de la compra.",
    )

    _pie(pdf, order.number)
    pdf.save()
    stream.seek(0)
    return stream
