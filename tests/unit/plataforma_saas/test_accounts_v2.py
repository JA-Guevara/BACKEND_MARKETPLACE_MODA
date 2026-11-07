import httpx
import pytest
from sqlalchemy import select
from fastapi import HTTPException

from src.infrastructure.config.settings import settings
from src.plataforma_saas.infrastructure.models.stripe_saas import TenantPaymentAccountModel
from src.ventas_pagos.infrastructure import gateways
from tests.unit.plataforma_saas.test_stripe_connect import activate


def test_gateway_v2_envia_json_y_version_sin_cambiar_pago_v1(monkeypatch):
    monkeypatch.setattr(settings,'stripe_secret_key','sk_test_unit_only')
    calls=[]
    def request(method,url,**kwargs):
        calls.append((url,kwargs))
        return httpx.Response(200,request=httpx.Request(method,url),json={'id':'acct_test'})
    monkeypatch.setattr(gateways.httpx,'request',request)
    body={'configuration':{'merchant':{'capabilities':{'card_payments':{'requested':True}}}}}
    gateways.stripe_request('POST','v2/core/accounts',body,key='once',api_version='2026-10-28.endive')
    gateways.stripe_request('POST','checkout/sessions',{'mode':'payment'},stripe_account='acct_company')
    assert calls[0][0]=='https://api.stripe.com/v2/core/accounts'
    assert calls[0][1]['json']==body and 'data' not in calls[0][1]
    assert calls[0][1]['headers']=={'Idempotency-Key':'once','Stripe-Version':'2026-10-28.endive'}
    assert calls[1][0]=='https://api.stripe.com/v1/checkout/sessions'
    assert calls[1][1]['data']=={'mode':'payment'} and 'json' not in calls[1][1]
    assert calls[1][1]['headers']['Stripe-Account']=='acct_company'


def test_gateway_rechaza_clave_real_antes_de_llamar_stripe(monkeypatch):
    monkeypatch.setattr(settings,'stripe_secret_key','sk_live_unit_only')
    monkeypatch.setattr(gateways.httpx,'request',lambda *a,**k:pytest.fail('No debe contactar Stripe live'))
    with pytest.raises(HTTPException) as error:
        gateways.stripe_request('POST','v2/core/accounts',{})
    assert error.value.status_code==503


@pytest.mark.parametrize('bad',[
    {'id':'acct_test','object':'v2.core.account','livemode':True},
    {'id':'acct_test','object':'account','livemode':False},
    {'id':'unknown','object':'v2.core.account','livemode':False},
])
def test_alta_no_guarda_respuesta_live_o_invalida(world,monkeypatch,bad):
    monkeypatch.setattr(settings,'stripe_secret_key','sk_test_unit_only')
    monkeypatch.setattr(settings,'stripe_connect_enabled',True)
    monkeypatch.setattr(gateways,'stripe_request',lambda *args,**kwargs:bad)
    response=world.client.post('/api/v1/tenant/payments/stripe-account/onboarding',headers=world.headers(world.admins[0]))
    assert response.status_code==409,response.text
    assert world.db.scalar(select(TenantPaymentAccountModel)) is None


def test_actualizar_estado_concilia_con_stripe_y_aisla_empresa_b(world,monkeypatch):
    a=activate(world,0);b=activate(world,1)
    a.charges_enabled=False;a.status='pending';world.db.commit()
    monkeypatch.setattr(settings,'stripe_secret_key','sk_test_unit_only')
    monkeypatch.setattr(settings,'stripe_connect_enabled',True)
    calls=[]
    def fresh(method,path,**kwargs):
        calls.append(path)
        return {'id':'acct_test_0','charges_enabled':True,'payouts_enabled':False,'details_submitted':True}
    monkeypatch.setattr(gateways,'stripe_request',fresh)
    response=world.client.get('/api/v1/tenant/payments/stripe-account',headers=world.headers(world.admins[0]))
    assert response.status_code==200,response.text
    assert response.json()['data']['charges_enabled'] is True
    world.db.expire_all()
    assert world.db.get(TenantPaymentAccountModel,a.tenant_id).status=='active'
    assert world.db.get(TenantPaymentAccountModel,b.tenant_id).payouts_enabled is True
    assert calls==['accounts/acct_test_0']


def test_cliente_no_inicia_alta_ni_consulta_cuenta_interna(world,monkeypatch):
    monkeypatch.setattr(gateways,'stripe_request',lambda *args,**kwargs:pytest.fail('Sin llamadas de clientes'))
    for method,path in [('POST','/onboarding'),('GET','')]:
        response=world.client.request(method,'/api/v1/tenant/payments/stripe-account'+path,headers=world.headers(world.customers[0]))
        assert response.status_code==403


def test_alta_de_dos_empresas_no_reutiliza_la_cuenta_de_otra(world,monkeypatch):
    monkeypatch.setattr(settings,'stripe_secret_key','sk_test_unit_only')
    monkeypatch.setattr(settings,'stripe_connect_enabled',True)
    monkeypatch.setattr(settings,'stripe_connect_test_country','US')
    creates=[];links=[]
    def stripe(method,path,data=None,key=None,**kwargs):
        if path=='v2/core/accounts':
            creates.append((data,key,kwargs))
            return {'id':'acct_company_'+str(len(creates)),'object':'v2.core.account','livemode':False}
        assert path=='account_links'
        links.append(data['account'])
        return {'url':'https://connect.stripe.com/setup/test','expires_at':2000000000}
    monkeypatch.setattr(gateways,'stripe_request',stripe)
    for user in [world.admins[0],world.admins[1],world.admins[0]]:
        response=world.client.post('/api/v1/tenant/payments/stripe-account/onboarding',headers=world.headers(user))
        assert response.status_code==200,response.text
    assert len(creates)==2 and links==['acct_company_1','acct_company_2','acct_company_1']
    for index,(body,key,kwargs) in enumerate(creates):
        assert body['metadata']=={'tenant_id':str(world.tenants[index].id)}
        assert body['contact_email']==world.tenants[index].contact_email
        assert body['identity']['country']=='us'
        assert str(world.tenants[index].id) in key
        assert kwargs['api_version']=='2026-10-28.endive'
        assert 'attestations' not in body['identity']


def test_actualizar_rechaza_cuenta_de_otra_empresa_sin_marcar_como_cobro_activo(world,monkeypatch):
    account=activate(world,0)
    account.status='pending';account.charges_enabled=False;world.db.commit()
    monkeypatch.setattr(settings,'stripe_secret_key','sk_test_unit_only')
    monkeypatch.setattr(settings,'stripe_connect_enabled',True)
    monkeypatch.setattr(gateways,'stripe_request',lambda *args,**kwargs:{'id':'acct_other','charges_enabled':True})
    response=world.client.get('/api/v1/tenant/payments/stripe-account',headers=world.headers(world.admins[0]))
    assert response.status_code==409,response.text
    world.db.expire_all()
    assert world.db.get(TenantPaymentAccountModel,account.tenant_id).charges_enabled is False
