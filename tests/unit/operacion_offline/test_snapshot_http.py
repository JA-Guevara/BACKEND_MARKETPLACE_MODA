from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel

def snapshot(world, **params):
    return world.client.get('/api/v1/offline/snapshot', params=params,
                            headers=world.headers(world.admins[0]))

def test_instantanea_aislada_con_documento_recortado(saas_world):
    w = saas_world
    response = snapshot(w, branch_id=str(w.branches[0].id))
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert data['full'] is True
    assert [p['id'] for p in data['products']] == [str(w.products[0].id)]
    assert [s['branch_id'] for s in data['stock']] == [str(w.branches[0].id)]
    assert data['variants'][0]['price'] is None
    assert data['customers'][0]['document_tail'] == '320'
    assert '987654320' not in response.text
    assert snapshot(w, branch_id=str(w.branches[1].id)).status_code == 404
    client = w.client.get('/api/v1/offline/snapshot', headers=w.headers(w.customers[0]))
    assert client.status_code == 200 and client.json()['data']['customers'] == []

def test_incremental_incluye_modificados_y_bajas(saas_world):
    w = saas_world
    first = snapshot(w).json()['data']
    w.products[0].name = 'Prenda actualizada'
    w.db.commit()
    data = snapshot(w, since=first['version']).json()['data']
    assert data['full'] is False
    assert [p['name'] for p in data['products']] == ['Prenda actualizada']
    w.products[0].is_active = False
    w.db.commit()
    removed = snapshot(w, since=data['version']).json()['data']
    assert str(w.products[0].id) in removed['removed']['products']
    assert removed['products'] == [] and removed['stock'] == []

def test_sin_token_suspension_y_version_futura(saas_world):
    w = saas_world
    assert w.client.get('/api/v1/offline/snapshot').status_code == 401
    assert snapshot(w, since=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()).status_code == 422
    sub = w.db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id == w.tenants[0].id))
    sub.status = 'SUSPENDIDA'
    w.db.commit()
    r = snapshot(w)
    assert r.status_code == 403 and r.json()['error']['code'] == 'subscription_inactive'
