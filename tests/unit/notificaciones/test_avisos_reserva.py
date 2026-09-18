"""CU15 y RF11 sobre una reserva real: quien recibe el aviso y con que contenido.

Se usa un remitente falso: lo que se verifica es la decision de a quien avisar,
no el envio SMTP.
"""
import uuid

import pytest
from sqlalchemy import select

from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.infrastructure.config.settings import settings
from src.notificaciones.application.use_cases.send_email import EnviarCorreo
from src.notificaciones.application.use_cases.send_notification import ServicioNotificaciones
from src.reservas.application.use_cases.confirm_reserva import ActualizarEstadoReserva
from src.reservas.application.use_cases.create_reserva import CrearReserva

from tests.unit.reservas.test_create_reserva_idempotencia import make_world, request


class RemitenteFalso:
    """Guarda lo que se habria enviado."""

    def __init__(self, exito: bool = True) -> None:
        self.exito = exito
        self.enviados: list[dict] = []

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        self.enviados.append({"to": to, "subject": subject, "body": body, "html": html or ""})
        return self.exito


class RemitenteCaido:
    def send(self, **_kwargs) -> bool:
        raise OSError("servidor de correo inalcanzable")


@pytest.fixture
def mundo():
    db, world = make_world()
    remitente = RemitenteFalso()
    servicio = ServicioNotificaciones(db, EnviarCorreo(db, remitente))
    return db, world, remitente, servicio


def crear_reserva(db, world):
    return CrearReserva(db).execute(
        world["actor"], request(world["branch"].id, world["variant"].id, str(uuid.uuid4()))
    )


def test_avisa_al_cliente_con_los_datos_de_la_cita(mundo):
    db, world, remitente, servicio = mundo
    reserva = crear_reserva(db, world)
    assert servicio.reserva(reserva) is True
    aviso = remitente.enviados[-1]
    assert aviso["to"] == world["actor"].email
    for version in (aviso["body"], aviso["html"]):
        assert world["branch"].name in version
        assert "Vestido primavera" in version


def test_la_sucursal_recibe_el_aviso_en_su_propia_casilla(mundo):
    db, world, remitente, servicio = mundo
    world["branch"].notification_email = "sucursal@fashionstore.test"
    db.commit()
    reserva = crear_reserva(db, world)
    servicio.reserva_a_sucursal(reserva)
    aviso = remitente.enviados[-1]
    assert aviso["to"] == "sucursal@fashionstore.test"
    assert "Ana Lopez" in aviso["body"]


def test_sin_casilla_de_sucursal_el_aviso_va_a_operaciones(mundo, monkeypatch):
    db, world, remitente, servicio = mundo
    monkeypatch.setattr(settings, "operations_email", "operaciones@fashionstore.test")
    reserva = crear_reserva(db, world)
    servicio.reserva_a_sucursal(reserva)
    assert remitente.enviados[-1]["to"] == "operaciones@fashionstore.test"


def test_sin_ningun_destinatario_no_se_envia_nada(mundo, monkeypatch):
    db, world, remitente, servicio = mundo
    monkeypatch.setattr(settings, "operations_email", None)
    reserva = crear_reserva(db, world)
    assert servicio.reserva_a_sucursal(reserva) is False
    assert remitente.enviados == []


def test_cada_cambio_de_estado_genera_su_propio_aviso(mundo):
    db, world, remitente, servicio = mundo
    reserva = crear_reserva(db, world)
    for estado in ("confirmed", "ready"):
        ActualizarEstadoReserva(db).execute(reserva, estado, world["actor"])
        servicio.reserva(reserva)
    asuntos = [a["subject"] for a in remitente.enviados]
    assert any("confirm" in s.lower() for s in asuntos)
    assert any("listas" in s.lower() for s in asuntos)


def test_el_envio_queda_registrado_en_bitacora(mundo):
    db, world, remitente, servicio = mundo
    reserva = crear_reserva(db, world)
    servicio.reserva(reserva)
    evento = db.scalars(
        select(AuditEventModel).where(AuditEventModel.action == "notificaciones.email_enviado")
    ).all()
    assert evento and evento[-1].entity_id == str(reserva.id)
    assert evento[-1].metadata_["sent"] is True


def test_un_servidor_de_correo_caido_no_rompe_la_operacion(mundo):
    db, world, _remitente, _servicio = mundo
    reserva = crear_reserva(db, world)
    caido = ServicioNotificaciones(db, EnviarCorreo(db, RemitenteCaido()))
    assert caido.reserva(reserva) is False
    fallidos = db.scalars(
        select(AuditEventModel).where(AuditEventModel.action == "notificaciones.email_fallido")
    ).all()
    assert fallidos


def test_crear_una_reserva_no_falla_aunque_no_haya_correo_configurado(mundo):
    """El flujo real usa el remitente SMTP; sin `smtp_host` devuelve False y la
    reserva igual debe quedar registrada."""
    db, world, _remitente, _servicio = mundo
    reserva = crear_reserva(db, world)
    assert reserva.id is not None
    assert reserva.status == "pending"
