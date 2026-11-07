import httpx
import pytest
from fastapi import HTTPException

from src.infrastructure.config.settings import settings
from src.ventas_pagos.infrastructure import gateways


@pytest.mark.parametrize('message,expected', [
    ('Stripe no longer recommends Accounts v1. Enable Accounts v1 support in the Dashboard.', 'Accounts v1 support'),
    ("You can only create new accounts if you've signed up for Connect.", 'Primero habilitá Stripe Connect'),
])
def test_configuracion_pendiente_explica_la_accion_sin_exponer_respuesta_stripe(monkeypatch, message, expected):
    monkeypatch.setattr(settings, 'stripe_secret_key', 'sk_test_unit_only')
    def unavailable(*args, **kwargs):
        request = httpx.Request('POST', 'https://api.stripe.com/v1/accounts')
        response = httpx.Response(400, request=request, json={'error': {'message': message+' Datos privados que no deben mostrarse.'}})
        raise httpx.HTTPStatusError('invalid setup', request=request, response=response)
    monkeypatch.setattr(gateways.httpx, 'request', unavailable)
    with pytest.raises(HTTPException) as caught:
        gateways.stripe_request('POST', 'accounts', {})
    assert caught.value.status_code == 409
    assert expected in caught.value.detail
    assert 'Datos privados' not in caught.value.detail


def test_otros_errores_siguen_siendo_genericos(monkeypatch):
    monkeypatch.setattr(settings, 'stripe_secret_key', 'sk_test_unit_only')
    def unavailable(*args, **kwargs):
        request = httpx.Request('POST', 'https://api.stripe.com/v1/accounts')
        response = httpx.Response(400, request=request, json={'error': {'message': 'Otra validación privada'}})
        raise httpx.HTTPStatusError('invalid', request=request, response=response)
    monkeypatch.setattr(gateways.httpx, 'request', unavailable)
    with pytest.raises(HTTPException) as caught:
        gateways.stripe_request('POST', 'accounts', {})
    assert caught.value.status_code == 502 and 'privada' not in caught.value.detail
