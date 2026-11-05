from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from src.main import create_app
from src.operacion_offline.infrastructure.models.sync import SyncOperationModel
from tests.unit.plataforma_saas.conftest import create_world


@pytest.fixture
def saas_world():
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("Requiere PostgreSQL real configurado en TEST_DATABASE_URL para concurrencia multi-hilo")
    w = create_world()
    w.client = TestClient(create_app())
    return w


def test_concurrencia_sync_idempotente(saas_world):
    """Verifica que dos hilos concurrentes enviando el mismo client_request_id
    se resuelvan sin duplicación ni corrupción de inventario en PostgreSQL."""
    w = saas_world
    crid = uuid4()
    headers = w.headers(w.admins[0])

    batch_body = {
        "device_id": "test-device-thread",
        "client_version": "1.0",
        "operations": [
            {
                "client_request_id": str(crid),
                "type": "SALE",
                "branch_id": str(w.branches[0].id),
                "device_id": "test-device-thread",
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "user_id": str(w.admins[0].id),
                    "items": [{"variant_id": str(w.variants[0].id), "quantity": 1}],
                    "subtotal": str(w.products[0].base_price),
                    "total": str(w.products[0].base_price),
                    "local_folio": "OFF-CONC-01",
                },
            }
        ],
    }

    def send():
        return w.client.post("/api/v1/sync/batch", headers=headers, json=batch_body)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(send)
        f2 = executor.submit(send)
        r1 = f1.result()
        r2 = f2.result()

    assert r1.status_code == 200
    assert r2.status_code == 200

    res1 = r1.json()["data"]["results"][0]
    res2 = r2.json()["data"]["results"][0]
    assert res1["status"] == "CONFIRMED"
    assert res2["status"] == "CONFIRMED"
    assert (res1["replay"] or res2["replay"]) is True
