"""Smoke test de la clave real de Stripe configurada en .env.

Usa una instancia propia de Settings (no el singleton cacheado de
src.infrastructure.config.settings) a proposito: otros tests de la suite
(test_commerce_contract.py, via qa_backend.py) neutralizan ese singleton para
aislar su propio entorno de pruebas, y como es un objeto compartido (@lru_cache)
esa neutralizacion persiste para el resto del proceso de pytest sin importar el
orden de ejecucion. Leer el .env de nuevo aqui evita depender de ese orden.
"""
import httpx
import pytest

from src.infrastructure.config.settings import Settings

settings = Settings()
pytestmark = pytest.mark.skipif(
    not settings.stripe_secret_key,
    reason="STRIPE_SECRET_KEY no configurada en .env; test omitido.",
)


def test_stripe_key_is_test_mode():
    assert settings.stripe_secret_key.startswith("sk_test_"), (
        "STRIPE_SECRET_KEY debe ser una clave de PRUEBA (sk_test_...). "
        "El proyecto rechaza claves live por diseno (ver gateways.stripe_request)."
    )


def test_stripe_key_is_valid():
    """Llamada real, de solo lectura, a la API de Stripe (consulta de balance):
    si la clave es invalida o fue revocada, Stripe responde 401 y falla el test."""
    response = httpx.get(
        "https://api.stripe.com/v1/balance",
        auth=(settings.stripe_secret_key, ""),
        timeout=20,
    )
    assert response.status_code == 200, (
        f"Stripe respondio {response.status_code}: {response.text[:300]}. "
        "Revisa STRIPE_SECRET_KEY en .env."
    )
    data = response.json()
    assert data["object"] == "balance"
    assert data["livemode"] is False, "La cuenta de Stripe respondio en modo LIVE; se esperaba modo test."
