"""Avisos que necesita la gestion interna, no el cliente.

Un pedido web deja prendas apartadas y una devolucion solicitada deja stock
inmovilizado: si nadie mira el panel, las dos cosas quedan detenidas. Estas
pruebas fijan a quien se avisa y con que datos se puede trabajar.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.infrastructure.config.settings import settings
from src.notificaciones.application.use_cases.send_email import EnviarCorreo
from src.notificaciones.application.use_cases.send_notification import ServicioNotificaciones
from src.ventas_pagos.application.returns_service import ReturnsService
from src.ventas_pagos.infrastructure.models import OrderModel, OrderReturnModel
from src.ventas_pagos.web.schemas import ReturnItemInput, ReturnRequest

from tests.unit.ventas_pagos.test_devoluciones import make_order, make_world


class RemitenteFalso:
    def __init__(self) -> None:
        self.enviados: list[dict] = []

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        self.enviados.append({"to": to, "subject": subject, "body": body, "html": html or ""})
        return True


@pytest.fixture
def mundo():
    db, world = make_world()
    remitente = RemitenteFalso()
    servicio = ServicioNotificaciones(db, EnviarCorreo(db, remitente))
    return db, world, remitente, servicio


def pedido_web(db, world, **cambios):
    """Un pedido del canal web, que es el que la sucursal tiene que preparar."""
    order = make_order(db, world, status="pending_payment", payment_status="pending", **cambios)
    order.sales_channel = "web"
    order.address = {
        "recipient": "Ana Perez", "phone": "700-12345",
        "line1": "Av. Monsenor Rivero 100", "city": "Santa Cruz", "country": "BO",
    }
    db.commit()
    db.refresh(order)
    return order


class TestPedidoALaSucursal:
    def test_la_sucursal_recibe_el_pedido_con_todo_lo_necesario(self, mundo):
        db, world, remitente, servicio = mundo
        world["branch"].notification_email = "central@fashionstore.test"
        db.commit()
        order = pedido_web(db, world)

        assert servicio.pedido_a_sucursal(order) is True
        aviso = remitente.enviados[-1]
        assert aviso["to"] == "central@fashionstore.test"
        assert order.number in aviso["subject"]
        for version in (aviso["body"], aviso["html"]):
            assert "Ana Perez" in version
            assert "Polera basica" in version
        # Lo que la sucursal necesita para preparar y despachar.
        assert "700-12345" in aviso["html"]
        assert "Av. Monsenor Rivero 100" in aviso["html"]

    def test_sin_casilla_propia_cae_en_operaciones(self, mundo, monkeypatch):
        db, world, remitente, servicio = mundo
        monkeypatch.setattr(settings, "operations_email", "operaciones@fashionstore.test")
        servicio.pedido_a_sucursal(pedido_web(db, world))
        assert remitente.enviados[-1]["to"] == "operaciones@fashionstore.test"

    def test_sin_ningun_destinatario_no_se_envia_nada(self, mundo, monkeypatch):
        db, world, remitente, servicio = mundo
        monkeypatch.setattr(settings, "operations_email", None)
        assert servicio.pedido_a_sucursal(pedido_web(db, world)) is False
        assert remitente.enviados == []

    def test_una_venta_de_caja_no_genera_aviso_de_preparacion(self, mundo):
        """Lo que se cobra en el mostrador ya se entrego: no hay nada que preparar."""
        db, world, remitente, servicio = mundo
        order = make_order(db, world)
        order.sales_channel = "pos"
        db.commit()
        servicio.pedido(order)
        # El cliente recibe su comprobante, no un aviso de estado.
        assert "Comprobante" in remitente.enviados[-1]["subject"]


class TestDevolucionAGestion:
    def solicitud(self, world):
        return ReturnRequest(
            reason="La talla no me quedo bien.",
            items=[ReturnItemInput(variant_id=world["variant"].id, quantity=1)],
        )

    def test_una_solicitud_avisa_al_cliente_y_a_gestion(self, mundo, monkeypatch):
        db, world, remitente, _servicio = mundo
        monkeypatch.setattr(settings, "operations_email", "operaciones@fashionstore.test")
        world["branch"].notification_email = "central@fashionstore.test"
        db.commit()
        order = make_order(db, world, cantidad=2)

        # El servicio real usa su propio remitente; se le inyecta el falso.
        service = ReturnsService(db)
        import src.ventas_pagos.application.returns_service as modulo

        avisos = []
        monkeypatch.setattr(
            modulo, "notificar_devolucion",
            lambda db_, dev, ord_, nota=None, avisar_gestion=False: avisos.append(avisar_gestion),
        )
        service.solicitar(world["cliente"], order, self.solicitud(world))
        assert avisos == [True], "la solicitud tiene que llegar a quien la resuelve"

    def test_el_aviso_interno_trae_pedido_cliente_y_motivo(self, mundo):
        db, world, remitente, servicio = mundo
        world["branch"].notification_email = "central@fashionstore.test"
        db.commit()
        order = make_order(db, world, cantidad=2)
        devolucion = ReturnsService(db).solicitar(
            world["cliente"], order, self.solicitud(world)
        )

        assert servicio.devolucion_a_gestion(devolucion, order) is True
        aviso = remitente.enviados[-1]
        assert aviso["to"] == "central@fashionstore.test"
        assert order.number in aviso["subject"]
        assert "La talla no me quedo bien." in aviso["html"]
        assert "100.00" in aviso["html"], "hay que ver cuanto se reintegra"

    def test_una_devolucion_de_mostrador_no_pide_revision(self, mundo, monkeypatch):
        """En caja ya se resolvio: avisar 'por revisar' seria ruido."""
        db, world, _remitente, _servicio = mundo
        order = make_order(db, world)
        import src.ventas_pagos.application.returns_service as modulo

        avisos = []
        monkeypatch.setattr(
            modulo, "notificar_devolucion",
            lambda db_, dev, ord_, nota=None, avisar_gestion=False: avisos.append(avisar_gestion),
        )
        from src.ventas_pagos.web.schemas import CounterReturn

        ReturnsService(db).registrar_en_caja(
            world["admin"], order,
            CounterReturn(
                order_id=order.id, reason="Cambio de talla.",
                items=[ReturnItemInput(variant_id=world["variant"].id, quantity=1)],
                client_request_id=uuid.uuid4(),
            ),
        )
        assert avisos == [False]


class TestBandejaDeGestion:
    """Filtros y contexto: lo que hace usable la bandeja cuando hay movimiento."""

    def test_filtra_por_estado_y_por_sucursal(self, mundo):
        db, world, _r, _s = mundo
        order = make_order(db, world, cantidad=2)
        service = ReturnsService(db)
        service.solicitar(world["cliente"], order, ReturnRequest(
            reason="Motivo de QA.",
            items=[ReturnItemInput(variant_id=world["variant"].id, quantity=1)],
        ))

        assert len(service.todas(status="requested")) == 1
        assert service.todas(status="completed") == []
        assert len(service.todas(branch_id=world["branch"].id)) == 1
        assert service.todas(branch_id=uuid.uuid4()) == []

    def test_busca_por_numero_de_pedido(self, mundo):
        db, world, _r, _s = mundo
        order = make_order(db, world, cantidad=2)
        service = ReturnsService(db)
        service.solicitar(world["cliente"], order, ReturnRequest(
            reason="Motivo de QA.",
            items=[ReturnItemInput(variant_id=world["variant"].id, quantity=1)],
        ))

        assert len(service.todas(q=order.number)) == 1
        assert service.todas(q="FS-NO-EXISTE") == []

    def test_cada_devolucion_llega_con_su_pedido_y_su_cliente(self, mundo):
        """Sin esto, la bandeja muestra un codigo suelto imposible de gestionar."""
        db, world, _r, _s = mundo
        order = make_order(db, world, cantidad=2)
        service = ReturnsService(db)
        devolucion = service.solicitar(world["cliente"], order, ReturnRequest(
            reason="Motivo de QA.",
            items=[ReturnItemInput(variant_id=world["variant"].id, quantity=1)],
        ))

        contexto = service.enriquecer([devolucion])[str(devolucion.id)]
        assert contexto["order_number"] == order.number
        assert contexto["customer_email"] == world["cliente"].email
        assert contexto["branch_name"] == world["branch"].name

    def test_una_bandeja_vacia_no_consulta_de_mas(self, mundo):
        db, _world, _r, _s = mundo
        assert ReturnsService(db).enriquecer([]) == {}
