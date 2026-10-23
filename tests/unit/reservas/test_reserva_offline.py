from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import select
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.ventas_pagos.infrastructure.models import StockModel, StockMovementModel

def payload(w, **changes):
    return dict(branch_id=str(w.branches[0].id),
                scheduled_at=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat(),
                items=[{'variant_id':str(w.variants[0].id),'quantity':2}],
                client_key=str(uuid4()), origin='OFFLINE', device_id='web-prueba',
                client_created_at=datetime.now(timezone.utc).isoformat(), **changes)

def test_reintento_offline_no_duplica_reserva_ni_stock(saas_world):
    w = saas_world
    p = payload(w)
    headers = w.headers(w.customers[0])
    first = w.client.post('/api/v1/reservations', headers=headers, json=p)
    assert first.status_code == 201, first.text
    data = first.json()['data']
    assert data['origin'] == 'OFFLINE' and data['device_id'] == 'web-prueba'
    replay = w.client.post('/api/v1/reservations', headers=headers, json=p)
    assert replay.status_code == 201 and replay.json()['data']['id'] == data['id']
    assert w.db.scalar(select(StockModel.quantity).where(StockModel.variant_id == w.variants[0].id)) == 18
    assert len(w.db.scalars(select(StockMovementModel)).all()) == 1
    p['items'][0]['quantity'] = 3
    assert w.client.post('/api/v1/reservations', headers=headers, json=p).status_code == 422

def test_campos_requeridos_y_compatibilidad_online(saas_world):
    w = saas_world
    p = payload(w)
    del p['device_id']
    assert w.client.post('/api/v1/reservations', headers=w.headers(w.customers[0]), json=p).status_code == 422
    for field in ('origin','client_created_at'):
        del p[field]
    r = w.client.post('/api/v1/reservations', headers=w.headers(w.customers[0]), json=p)
    assert r.status_code == 201 and r.json()['data']['origin'] == 'ONLINE'

def test_empleado_cliente_y_empresa_ajena(saas_world):
    w = saas_world
    p = payload(w, customer_id=str(w.customers[0].id))
    assert w.client.post('/api/v1/reservations', headers=w.headers(w.customers[0]), json=p).status_code == 403
    r = w.client.post('/api/v1/reservations', headers=w.headers(w.admins[0]), json=p)
    assert r.status_code == 201, r.text
    saved = w.db.get(ReservationModel, __import__('uuid').UUID(r.json()['data']['id']))
    assert saved.user_id == w.customers[0].id and saved.created_by_id == w.admins[0].id
    p['customer_id'] = str(w.customers[1].id)
    assert w.client.post('/api/v1/reservations', headers=w.headers(w.admins[0]), json=p).status_code == 404
