"""Demostración de la mejora: una transcripción lenta ya no frena al resto.

`transcribe_assistant_audio` espera a OpenAI con `httpx.post` síncrono, hasta
`settings.ai_timeout` y con un reintento contra el segundo modelo. Mientras el
endpoint era `async def`, esa espera ocurría dentro del bucle de eventos y
detenía TODAS las peticiones del proceso, incluido `/health` -el chequeo de
salud de Railway-. Declarado `def`, FastAPI lo ejecuta en su pool de hilos.

Esta prueba lo comprueba de verdad: deja una transcripción esperando y pide
`/health` en paralelo. Si alguien vuelve a poner `async def`, la respuesta de
`/health` queda detrás de la espera y la prueba falla.
"""

import threading
import time
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.config.settings import settings
from src.main import create_app
from src.ventas_pagos.web import router

ESPERA_IA = 1.5   # lo que "tarda" la IA simulada
MARGEN = 0.5      # techo tolerado para /health mientras la IA sigue esperando


class _RespuestaIA:
    def raise_for_status(self):
        return None

    def json(self):
        return {"text": "Exportame ventas de este mes en Excel"}


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(settings, "ai_api_key", "test-key", raising=False)
    usuario = UserModel(email="cliente@example.test", password_hash="unused", first_name="Cliente",
                        last_name="Prueba", is_active=True, is_verified=True)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: usuario
    with TestClient(app) as client:
        yield client


def test_una_transcripcion_lenta_no_frena_el_chequeo_de_salud(cliente, monkeypatch):
    llamando = threading.Event()

    def ia_lenta(*_args, **_kwargs):
        llamando.set()
        time.sleep(ESPERA_IA)
        return _RespuestaIA()

    monkeypatch.setattr(router.httpx, "post", ia_lenta)

    resultado = {}

    def transcribir():
        resultado["respuesta"] = cliente.post(
            "/api/v1/commerce/assistant/transcribe",
            files={"audio": ("consulta.webm", BytesIO(b"a" * 600), "audio/webm")},
        )

    hilo = threading.Thread(target=transcribir)
    hilo.start()
    try:
        # Solo se mide cuando la petición ya está detenida esperando a la IA.
        assert llamando.wait(timeout=5), "La transcripción nunca llegó a llamar a la IA."
        inicio = time.monotonic()
        salud = cliente.get("/health")
        demora = time.monotonic() - inicio
    finally:
        hilo.join(timeout=ESPERA_IA + 10)

    assert salud.status_code == 200 and salud.json() == {"status": "ok"}
    assert demora < MARGEN, (
        f"/health tardó {demora:.2f} s mientras se transcribía: el endpoint volvió a bloquear "
        "el bucle de eventos."
    )
    assert resultado["respuesta"].status_code == 200
    assert resultado["respuesta"].json()["data"] == {
        "available": True,
        "text": "Exportame ventas de este mes en Excel",
    }
