"""Smoke test de la clave real de OpenAI configurada en .env.

Usa una instancia propia de Settings (no el singleton cacheado), por la misma
razon que test_stripe_connection.py: el singleton puede quedar neutralizado por
qa_backend.py (via test_commerce_contract.py) para el resto del proceso de
pytest, sin importar el orden de ejecucion de los tests.
"""
from dotenv import dotenv_values
import httpx
import pytest

from src.infrastructure.config.settings import Settings

_file_env = dotenv_values(".env")
settings = Settings()
if not settings.ai_api_key and _file_env.get("AI_API_KEY"):
    settings.ai_api_key = _file_env["AI_API_KEY"]
if _file_env.get("AI_BASE_URL"):
    settings.ai_base_url = _file_env["AI_BASE_URL"]
if _file_env.get("AI_MODEL"):
    settings.ai_model = _file_env["AI_MODEL"]

pytestmark = pytest.mark.skipif(
    not settings.ai_api_key,
    reason="AI_API_KEY no configurada en .env; test omitido.",
)


def test_openai_key_is_valid():
    """Llamada real y minima para confirmar que la clave y el
    modelo configurados responden. Es el mismo endpoint que usan /analytics/insights
    y /commerce/assistant."""
    response = httpx.post(
        settings.ai_chat_completions_url,
        headers={"Authorization": "Bearer " + settings.ai_api_key},
        json={
            "model": settings.ai_model,
            "messages": [{"role": "user", "content": "Responde solo con la palabra: ok"}],
            "max_tokens": 1000,
            "reasoning_effort": "low",
        },
        timeout=25,
    )
    assert response.status_code == 200, (
        f"El proveedor de IA ({settings.ai_base_url}) respondio {response.status_code}: {response.text[:300]}. "
        "Revisa AI_API_KEY, AI_BASE_URL y AI_MODEL en .env."
    )
    content = response.json()["choices"][0]["message"]["content"]
    assert content.strip() != ""
