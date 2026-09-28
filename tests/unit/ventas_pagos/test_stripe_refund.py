import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.ventas_pagos.infrastructure import gateways


def entities():
    order = SimpleNamespace(id=uuid.uuid4(), payment_reference="pi_test", currency="BOB")
    returned = SimpleNamespace(id=uuid.uuid4(), refund_amount=Decimal("80.00"))
    return order, returned


def test_reembolso_stripe_usa_importe_pagado_y_clave_idempotente(monkeypatch):
    order, returned = entities()
    calls = []

    def stripe(method, path, data=None, key=None):
        calls.append((method, path, data, key))
        if method == "GET":
            return {"data": []}
        return {"id": "re_test", "payment_intent": "pi_test", "amount": 8000,
                "currency": "bob", "status": "succeeded"}

    monkeypatch.setattr(gateways, "stripe_request", stripe)
    assert gateways.refund_order_return(order, returned) == "re_test"
    assert calls[-1] == ("POST", "refunds", {
        "payment_intent": "pi_test", "amount": "8000",
        "reason": "requested_by_customer", "metadata[return_id]": str(returned.id),
        "metadata[order_id]": str(order.id),
    }, f"fashion-return-{returned.id}")


def test_reintento_encuentra_reembolso_existente_sin_crear_otro(monkeypatch):
    order, returned = entities()
    calls = []

    def stripe(method, path, data=None, key=None):
        calls.append(method)
        return {"data": [{"id": "re_test", "metadata": {"return_id": str(returned.id)},
                          "payment_intent": "pi_test", "amount": 8000,
                          "currency": "bob", "status": "succeeded"}]}

    monkeypatch.setattr(gateways, "stripe_request", stripe)
    assert gateways.refund_order_return(order, returned) == "re_test"
    assert calls == ["GET"]


def test_reembolso_pendiente_no_cierra_el_caso(monkeypatch):
    order, returned = entities()
    monkeypatch.setattr(gateways, "stripe_request", lambda *_, **__: {
        "data": [{"id": "re_test", "metadata": {"return_id": str(returned.id)},
                  "payment_intent": "pi_test", "amount": 8000,
                  "currency": "bob", "status": "pending"}],
    })
    with pytest.raises(HTTPException) as error:
        gateways.refund_order_return(order, returned)
    assert error.value.status_code == 409
