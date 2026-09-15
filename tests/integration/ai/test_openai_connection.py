"""Smoke test de la clave real de OpenAI configurada en .env.

Usa una instancia propia de Settings (no el singleton cacheado), por la misma
razon que test_stripe_connection.py: el singleton puede quedar neutralizado por
qa_backend.py (via test_commerce_contract.py) para el resto del proceso de
pytest, sin importar el orden de ejecucion de los tests.
"""
import httpx
import pytest

from src.infrastructure.config.settings import Settings

settings = Settings()
pytestmark = pytest.mark.skipif(
    not settings.ai_api_key,
    reason="AI_API_KEY no configurada en .env; test omitido.",
)


def test_openai_key_is_valid():
    """Llamada real y minima (max_tokens bajo) para confirmar que la clave y el
    modelo configurados responden. Es el mismo endpoint que usan /analytics/insights
    y /commerce/assistant."""
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": "Bearer " + settings.ai_api_key},
        json={
            "model": settings.ai_model,
            "messages": [{"role": "user", "content": "Responde solo con la palabra: ok"}],
            "max_tokens": 5,
        },
        timeout=25,
    )
    assert response.status_code == 200, (
        f"OpenAI respondio {response.status_code}: {response.text[:300]}. "
        "Revisa AI_API_KEY y AI_MODEL en .env."
    )
    content = response.json()["choices"][0]["message"]["content"]
    assert content.strip() != ""
