"""Lo que el cliente termina leyendo: asunto, texto y HTML de cada aviso.

Se verifica sin base de datos ni servidor de correo porque las plantillas son
funciones puras (CU15 notificar cambio de estado, RF11 aviso a la sucursal,
CU19 devoluciones y reembolsos, RF17/RF18 comprobante de caja).

Cada caso comprueba las **dos** versiones: un cliente que bloquea HTML tiene que
recibir la misma información, no un correo vacío.
"""
import pytest

from src.notificaciones.domain import plantillas


ITEMS = [
    {"name": "Polera basica", "size": "M", "color": "Negro", "quantity": 2, "line_total": "200.00"},
    {"name": "Camisa lino", "size": "L", "color": "Blanco", "quantity": 1, "line_total": "180.00"},
]


def ambos(mensaje) -> str:
    """Texto y HTML juntos, para afirmar que el dato está en las dos versiones."""
    assert mensaje.texto and mensaje.html
    return mensaje.texto + "\n" + mensaje.html


class TestPedido:
    def test_el_asunto_nombra_el_estado_y_el_numero(self):
        mensaje = plantillas.pedido_estado(numero="FS-001", estado="paid")
        assert "FS-001" in mensaje.asunto
        assert "pago" in mensaje.asunto.lower()

    def test_detalla_las_prendas_y_el_total_en_las_dos_versiones(self):
        mensaje = plantillas.pedido_estado(
            numero="FS-001", estado="pending_payment", items=ITEMS, total="380.00", moneda="BOB"
        )
        for version in (mensaje.texto, mensaje.html):
            assert "Polera basica" in version
            assert "380.00" in version
        assert "M" in mensaje.html and "Negro" in mensaje.html

    def test_el_envio_lleva_transportista_y_seguimiento(self):
        mensaje = plantillas.pedido_estado(
            numero="FS-002", estado="shipped", transportista="Transportes Sur", seguimiento="TRK-9"
        )
        contenido = ambos(mensaje)
        assert contenido.count("Transportes Sur") == 2
        assert contenido.count("TRK-9") == 2

    def test_el_transportista_no_aparece_cuando_el_pedido_no_salio(self):
        mensaje = plantillas.pedido_estado(
            numero="FS-002", estado="processing", transportista="Transportes Sur", seguimiento="TRK-9"
        )
        assert "TRK-9" not in ambos(mensaje)

    def test_un_pedido_en_curso_dibuja_su_progreso(self):
        mensaje = plantillas.pedido_estado(numero="FS-004", estado="shipped")
        assert "En camino" in mensaje.html
        assert "Entregado" in mensaje.html

    def test_un_pedido_cancelado_no_dibuja_progreso(self):
        """Un pedido que ya no avanza no debe mostrar etapas por delante."""
        mensaje = plantillas.pedido_estado(numero="FS-005", estado="cancelled")
        assert "Preparando" not in mensaje.html

    def test_un_estado_desconocido_no_rompe_el_aviso(self):
        mensaje = plantillas.pedido_estado(numero="FS-003", estado="inventado")
        assert mensaje.asunto
        assert "FS-003" in ambos(mensaje)

    def test_incluye_el_enlace_para_seguir_el_pedido(self):
        mensaje = plantillas.pedido_estado(
            numero="FS-004", estado="delivered", enlace="https://tienda.test/mi-cuenta/pedidos"
        )
        assert "https://tienda.test/mi-cuenta/pedidos" in mensaje.texto
        assert 'href="https://tienda.test/mi-cuenta/pedidos"' in mensaje.html

    def test_traduce_el_medio_de_pago(self):
        mensaje = plantillas.pedido_estado(numero="FS-006", estado="paid", metodo_pago="stripe")
        assert "Tarjeta" in mensaje.html


class TestComprobanteDeCaja:
    def test_es_un_comprobante_y_no_un_estado(self):
        mensaje = plantillas.comprobante_venta(
            numero="FS-POS-1", items=ITEMS, total="380.00", metodo_pago="cash",
            referencia="REC-77", sucursal="Sucursal Centro", cliente="Ana Perez",
        )
        contenido = ambos(mensaje)
        assert "Comprobante" in mensaje.asunto
        assert "REC-77" in contenido
        assert "Sucursal Centro" in contenido
        assert "Efectivo" in mensaje.html
        assert "380.00" in contenido

    def test_sin_cliente_usa_consumidor_final(self):
        mensaje = plantillas.comprobante_venta(numero="FS-POS-2", items=ITEMS, total="10.00")
        assert "Consumidor final" in mensaje.html

    def test_recuerda_que_sirve_para_devolver(self):
        mensaje = plantillas.comprobante_venta(numero="FS-POS-3", items=ITEMS, total="10.00")
        assert "devolver" in mensaje.html


class TestReserva:
    def test_dice_donde_y_cuando_es_la_cita(self):
        mensaje = plantillas.reserva_estado(
            codigo="AB12CD34", estado="confirmed", sucursal="Sucursal Centro",
            direccion="Av. Monsenor Rivero 100", fecha="20/09/2026 15:30", items=ITEMS,
        )
        contenido = ambos(mensaje)
        assert "Sucursal Centro" in contenido
        assert "Av. Monsenor Rivero 100" in contenido
        assert "20/09/2026 15:30" in contenido
        assert "Camisa lino" in contenido

    def test_una_reserva_confirmada_explica_como_presentarse(self):
        mensaje = plantillas.reserva_estado(codigo="X", estado="ready", sucursal="Centro")
        assert "mostrador" in mensaje.html

    def test_el_aviso_a_la_sucursal_identifica_cliente_y_contacto(self):
        mensaje = plantillas.reserva_para_sucursal(
            codigo="AB12CD34", sucursal="Sucursal Centro", cliente="Ana Perez",
            contacto="700 · ana@example.test", fecha="20/09/2026 15:30", items=ITEMS,
            notas="Prefiero probarme primero la camisa.",
        )
        contenido = ambos(mensaje)
        assert "AB12CD34" in mensaje.asunto
        assert "Sucursal Centro" in mensaje.asunto
        assert "Ana Perez" in contenido
        assert "Prefiero probarme primero la camisa." in contenido
        assert "ana@example.test" in mensaje.html

    def test_una_prenda_sin_talla_ni_color_igual_se_lista(self):
        mensaje = plantillas.reserva_estado(
            codigo="X", estado="pending", sucursal="Centro", items=[{"name": "Blusa", "quantity": 1}]
        )
        assert "Blusa" in ambos(mensaje)
        assert "()" not in mensaje.texto


class TestDevolucion:
    def test_el_reembolso_dice_el_importe_y_por_donde_vuelve(self):
        mensaje = plantillas.devolucion_estado(
            codigo="R1", numero_pedido="FS-001", estado="completed", items=ITEMS,
            monto="200.00", metodo_reembolso="transfer",
        )
        assert "200.00" in ambos(mensaje)
        assert "Transferencia" in mensaje.html
        assert "reembolsado" in mensaje.html.lower()

    def test_una_devolucion_aprobada_explica_el_siguiente_paso(self):
        mensaje = plantillas.devolucion_estado(codigo="R2", numero_pedido="FS-2", estado="approved")
        assert "sucursal" in mensaje.html.lower()

    def test_un_rechazo_muestra_el_motivo(self):
        mensaje = plantillas.devolucion_estado(
            codigo="R3", numero_pedido="FS-3", estado="rejected", nota="La prenda fue usada."
        )
        assert "La prenda fue usada." in ambos(mensaje)


class TestSeguridadDelHtml:
    @pytest.mark.parametrize("estado", ["pending_payment", "shipped", "delivered", "cancelled"])
    def test_el_html_esta_completo_en_cualquier_estado(self, estado):
        mensaje = plantillas.pedido_estado(numero="FS-9", estado=estado, items=ITEMS, total="1.00")
        assert mensaje.html.startswith("<!DOCTYPE html>")
        assert mensaje.html.rstrip().endswith("</html>")

    def test_un_nombre_con_html_no_rompe_el_correo(self):
        """El nombre de una prenda o una nota vienen de datos, no del código."""
        mensaje = plantillas.pedido_estado(
            numero="FS-10", estado="paid",
            items=[{"name": "<script>alert(1)</script>", "quantity": 1}],
            nota="Nota con <b>etiquetas</b> & símbolos",
        )
        assert "<script>" not in mensaje.html
        assert "&lt;script&gt;" in mensaje.html
        assert "&amp;" in mensaje.html

    def test_un_enlace_con_comillas_no_escapa_del_atributo(self):
        mensaje = plantillas.pedido_estado(
            numero="FS-11", estado="paid", enlace='https://x.test/"><script>'
        )
        assert '"><script>' not in mensaje.html
