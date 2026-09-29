"""La ruta HTTP del webhook de Stripe valida la firma sobre los bytes exactos.

El handler pasó a delegar el trabajo pesado (HMAC, bloqueo del pedido, correo)
al pool de hilos con `run_in_threadpool`. El riesgo de ese cambio es que el
cuerpo deje de llegar tal cual: Stripe firma los BYTES crudos, así que basta con
que alguien vuelva a serializar el JSON -otro orden de claves, otros espacios-
para que la firma deje de validar y el cobro se caiga sin aviso. Esta prueba
manda un cuerpo con espaciado deliberadamente irregular: solo pasa si esos
mismos bytes llegan intactos a verify_event.
"""

import hashlib
import hmac
import time
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.config.settings import settings
from src.infrastructure.database.base import Base
from src.infrastructure.database.session import get_db
from src.main import create_app
from src.ventas_pagos.infrastructure.models import OrderModel

SECRETO = "whsec_prueba_local"
RUTA = "/api/v1/commerce/stripe/webhook"


def _cuerpo_con_espaciado_irregular(session_id: str) -> bytes:
    # A propósito NO se usa json.dumps: este espaciado no lo genera ningún
    # serializador, así que si el cuerpo se reconstruyera en algún punto los
    # bytes cambiarían y el HMAC fallaría.
    return (
        '{"id": "evt_prueba",   "type": "checkout.session.completed",'
        ' "livemode": false,'
        ' "data": {"object": {"id": "' + session_id + '", "payment_status": "paid"}}}'
    ).encode()


def _firma(cuerpo: bytes, secreto: str = SECRETO) -> str:
    marca = str(int(time.time()))
    esperada = hmac.new(secreto.encode(), marca.encode() + b"." + cuerpo, hashlib.sha256).hexdigest()
    return f"t={marca},v1={esperada}"


@pytest.fixture
def mundo(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", SECRETO, raising=False)
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = UserModel(email="cliente@example.test", password_hash="unused", first_name="Cliente",
                         last_name="Prueba", is_active=True, is_verified=True)
        db.add(user)
        db.flush()
        # Pedido ya pagado: el evento se registra y se deduplica, pero no cambia
        # el estado, así que no dispara ningún correo real durante la prueba.
        order = OrderModel(number="FS-WH", user_id=user.id, customer_email=user.email,
                           branch_id=uuid.uuid4(), payment_method="stripe", status="paid",
                           payment_status="paid", total=Decimal("120"), currency="bob",
                           address={}, items=[], stripe_session_id="cs_test_webhook", tracking=[])
        db.add(order)
        db.commit()
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield client, db, order
    engine.dispose()


def test_la_firma_se_valida_sobre_los_bytes_crudos_del_cuerpo(mundo):
    client, _, order = mundo
    cuerpo = _cuerpo_con_espaciado_irregular(order.stripe_session_id)
    respuesta = client.post(RUTA, content=cuerpo,
                            headers={"stripe-signature": _firma(cuerpo),
                                     "content-type": "application/json"})
    assert respuesta.status_code == 200, respuesta.text
    # Contrato propio de Stripe: dict crudo, sin el sobre {success,message,data}.
    assert respuesta.json() == {"received": True}


def test_el_reintento_del_mismo_evento_se_marca_duplicado(mundo):
    client, _, order = mundo
    cuerpo = _cuerpo_con_espaciado_irregular(order.stripe_session_id)
    client.post(RUTA, content=cuerpo, headers={"stripe-signature": _firma(cuerpo),
                                               "content-type": "application/json"})
    repetido = client.post(RUTA, content=cuerpo, headers={"stripe-signature": _firma(cuerpo),
                                                          "content-type": "application/json"})
    assert repetido.status_code == 200
    assert repetido.json() == {"received": True, "duplicate": True}


def test_una_firma_de_otro_secreto_sigue_dando_400(mundo):
    client, _, order = mundo
    cuerpo = _cuerpo_con_espaciado_irregular(order.stripe_session_id)
    respuesta = client.post(RUTA, content=cuerpo,
                            headers={"stripe-signature": _firma(cuerpo, "whsec_otro"),
                                     "content-type": "application/json"})
    assert respuesta.status_code == 400
    assert respuesta.json()["detail"] == "Firma Stripe invalida."


def test_un_cuerpo_alterado_despues_de_firmar_sigue_dando_400(mundo):
    client, _, order = mundo
    cuerpo = _cuerpo_con_espaciado_irregular(order.stripe_session_id)
    firma = _firma(cuerpo)
    respuesta = client.post(RUTA, content=cuerpo.replace(b'"paid"', b'"unpaid"'),
                            headers={"stripe-signature": firma,
                                     "content-type": "application/json"})
    assert respuesta.status_code == 400
