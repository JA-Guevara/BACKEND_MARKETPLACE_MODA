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


def test_cursor_compuesto_no_pierde_ventas_con_fecha_igual(world):
    from datetime import datetime,timezone
    from src.ventas_pagos.infrastructure.models import OrderModel
    from decimal import Decimal
    moment=datetime.now(timezone.utc)
    orders=[]
    for i in range(5):
        row=OrderModel(tenant_id=world.tenants[0].id,number='TIE-'+str(i),user_id=world.customers[0].id,branch_id=world.branches[0].id,customer_email=world.customers[0].email,payment_method='cash',sales_channel='pos',total=Decimal('10'),currency='BOB',status='paid',payment_status='paid',paid_at=moment)
        world.db.add(row);orders.append(row)
    world.db.commit();_,raw=key(world,['sales:read'])
    seen=[];cursor=None
    for _ in range(4):
        params={'limit':2}
        if cursor:params['since']=cursor
        response=world.client.get('/api/v1/integrations/v1/sales',params=params,headers={'X-API-Key':raw})
        assert response.status_code==200,response.text
        payload=response.json()['data'];seen.extend(item['id'] for item in payload['items']);cursor=payload['next_since']
        if not cursor:break
    assert len(seen)==5 and len(set(seen))==5 and set(seen)=={str(row.id) for row in orders}
