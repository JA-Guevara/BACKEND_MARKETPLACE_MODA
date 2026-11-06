from tests.unit.plataforma_saas.conftest import world
from tests.unit.plataforma_saas.test_stripe_connect import pending_order
from src.integraciones.application.api_keys_service import ApiKeysService


def key(w,scopes):
    return ApiKeysService(w.db).crear(w.tenants[0].id,'Sistema prueba',scopes)


def test_clave_ventas_solo_empresa_propietaria(world):
    a=pending_order(world,0);b=pending_order(world,1)
    a.status=b.status='paid';a.payment_status=b.payment_status='paid'
    from datetime import datetime,timezone
    a.paid_at=b.paid_at=datetime.now(timezone.utc);world.db.commit()
    _,raw=key(world,['sales:read'])
    response=world.client.get('/api/v1/integrations/v1/sales',headers={'Authorization':'Bearer '+raw})
    assert response.status_code==200,response.text
    assert [row['id'] for row in response.json()['data']['items']]==[str(a.id)]


def test_clave_scope_insuficiente(world):
    _,raw=key(world,['sales:read'])
    response=world.client.get('/api/v1/integrations/v1/stock',headers={'X-API-Key':raw})
    assert response.status_code==403 and response.json()['error']['code']=='api_key_scope'


def test_clave_revocada_rechazada(world):
    model,raw=key(world,['stock:read']);ApiKeysService(world.db).revocar(world.tenants[0].id,model.id)
    response=world.client.get('/api/v1/integrations/v1/stock',headers={'X-API-Key':raw})
    assert response.status_code==401 and response.json()['error']['code']=='api_key_invalid'


def test_no_se_puede_suplantar_tenant_por_query_o_cabecera(world):
    _,raw=key(world,['stock:read'])
    response=world.client.get('/api/v1/integrations/v1/stock?tenant_id='+str(world.tenants[1].id),headers={'X-API-Key':raw,'X-Tenant-Id':str(world.tenants[1].id)})
    assert response.status_code==200,response.text
    assert {row['sku'] for row in response.json()['data']['items']}=={world.variants[0].sku}
