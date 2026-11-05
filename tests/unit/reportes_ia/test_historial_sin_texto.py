import hashlib
import uuid

from src.reportes_ia.infrastructure.models import ReportRequestModel


def test_el_historial_no_guarda_ni_devuelve_el_texto_de_la_consulta(saas_world):
    world = saas_world
    admin = world.admins[1]
    headers = world.headers(admin)
    texto = "Mostrame las ventas por sucursal de este mes con nombres de clientes"

    respuesta = world.client.post(
        "/api/v1/analytics/ai-reports/interpret",
        headers=headers,
        json={"text": texto, "channel": "TEXT"},
    )
    assert respuesta.status_code == 200, respuesta.text
    request_id = respuesta.json()["data"]["request_id"]

    fila = world.db.get(ReportRequestModel, uuid.UUID(request_id))
    assert fila is not None
    assert fila.prompt_sha256 == hashlib.sha256(texto.encode("utf-8")).hexdigest()
    assert fila.prompt_length == len(texto)
    assert texto not in repr(fila.__dict__)

    historial = world.client.get("/api/v1/analytics/ai-reports/history", headers=headers)
    assert historial.status_code == 200, historial.text
    item = next(i for i in historial.json()["data"]["items"] if i["id"] == request_id)
    assert "prompt_text" not in item
    assert item["prompt_length"] == len(texto)
    assert texto not in historial.text
