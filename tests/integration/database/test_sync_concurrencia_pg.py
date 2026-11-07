from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock, get_ident
from datetime import datetime, timezone
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from src.main import create_app
from src.infrastructure.database.safety import require_local_database
from src.infrastructure.database.session import get_db
from src.dispositivos.infrastructure.models import DeviceModel
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.operacion_offline.infrastructure.models.sync import SyncOperationModel
from tests.unit.plataforma_saas.conftest import create_world


@pytest.fixture
def saas_world():
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("Requiere PostgreSQL real configurado en TEST_DATABASE_URL para concurrencia multi-hilo")
    url = make_url(os.environ["TEST_DATABASE_URL"])
    require_local_database(url, allow_remote=False)
    name = 'ps_sync_qa_' + uuid4().hex
    admin = create_engine(url, isolation_level='AUTOCOMMIT')
    engine = None
    w = None
    try:
        with admin.connect() as c:
            c.execute(text(f'CREATE DATABASE "{name}"'))
        engine = create_engine(url.set(database=name))
        w = create_world(engine=engine)
        app = create_app()

        def separate_session():
            with Session(engine, expire_on_commit=False) as db:
                yield db

        app.dependency_overrides[get_db] = separate_session
        w.client = TestClient(app)
        yield w
    finally:
        if w is not None:
            w.db.close()
        if engine is not None:
            engine.dispose()
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


@pytest.fixture
def simultaneous_device_registration(saas_world):
    """Fuerza ambos primeros accesos antes del alta, sin depender del scheduler."""
    barrier = Barrier(2, timeout=15)
    guard = Lock()
    participants = set()

    def after_device_read(connection, cursor, statement, parameters, context, executemany):
        if not statement.lstrip().startswith("SELECT") or "FROM devices " not in statement:
            return
        with guard:
            thread = get_ident()
            wait = len(participants) < 2 and thread not in participants
            if wait:
                participants.add(thread)
        if wait:
            barrier.wait()

    event.listen(saas_world.engine, "after_cursor_execute", after_device_read)
    try:
        yield
    finally:
        event.remove(saas_world.engine, "after_cursor_execute", after_device_read)


def test_concurrencia_sync_idempotente(saas_world, simultaneous_device_registration):
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

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text

    res1 = r1.json()["data"]["results"][0]
    res2 = r2.json()["data"]["results"][0]
    assert res1["status"] == "CONFIRMED"
    assert res2["status"] == "CONFIRMED"
    assert (res1["replay"] or res2["replay"]) is True
    assert w.db.scalar(select(func.count()).select_from(SyncOperationModel).where(
        SyncOperationModel.client_request_id == crid,
    )) == 1
    device = w.db.scalar(select(DeviceModel).where(
        DeviceModel.tenant_id == w.tenant_a.id, DeviceModel.device_id == "test-device-thread",
    ))
    assert device is not None
    assert w.db.scalar(select(func.count()).select_from(AuditEventModel).where(
        AuditEventModel.tenant_id == w.tenant_a.id,
        AuditEventModel.action == "devices.registered", AuditEventModel.entity_id == str(device.id),
    )) == 1


def test_different_sales_competing_for_last_stock_do_not_oversell(saas_world, simultaneous_device_registration):
    w = saas_world
    def send():
        return w.client.post("/api/v1/sync/batch", headers=w.headers(w.admin_a), json={
            "device_id": "offline-stock-qa", "client_version": "qa", "operations": [{
                "client_request_id": str(uuid4()), "type": "SALE", "branch_id": str(w.branch_a.id),
                "device_id": "offline-stock-qa", "client_created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {"user_id": str(w.admin_a.id), "cash_point_id": str(w.cash_point_a.id),
                            "items": [{"variant_id": str(w.variant_a.id), "quantity": 15, "unit_price": "150.00"}],
                            "total": "2250.00", "cash_received": "2250.00"},
            }],
        })
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: send(), range(2)))
    assert all(response.status_code == 200 for response in responses), [(r.status_code, r.text) for r in responses]
    statuses = sorted(response.json()["data"]["results"][0]["status"] for response in responses)
    assert statuses == ["CONFIRMED", "CONFLICT"]
    from src.ventas_pagos.infrastructure.models import StockModel
    assert w.db.scalar(select(StockModel.quantity).where(StockModel.variant_id == w.variant_a.id)) == 5
