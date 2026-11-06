from datetime import datetime, timezone
from decimal import Decimal
import time
from sqlalchemy import select
from src.infrastructure.config.settings import settings
from src.ventas_pagos.infrastructure import gateways
from src.ventas_pagos.infrastructure.models import OrderModel
from src.ventas_pagos.application.service import CommerceService
from tests.unit.plataforma_saas.test_stripe_billing import post_event


def pending_order(w,number=0):
    order=OrderModel(tenant_id=w.tenants[number].id,number='ORDER-UNIT-'+str(number),user_id=w.customers[number].id,branch_id=w.branches[number].id,customer_email=w.customers[number].email,payment_method='stripe',sales_channel='web',total=Decimal('150'),subtotal=Decimal('150'),discount_total=0,discounts=[],currency='BOB',address={},items=[],tracking=[],status='pending_payment',payment_status='pending')
    w.db.add(order);w.db.commit();return order


def activate(w,number=0):
    from src.plataforma_saas.infrastructure.models.stripe_saas import TenantPaymentAccountModel
    account=TenantPaymentAccountModel(tenant_id=w.tenants[number].id,stripe_account_id='acct_test_'+str(number),status='active',charges_enabled=True,payouts_enabled=True,details_submitted=True,updated_at=datetime.now(timezone.utc))
    w.db.add(account);w.db.commit();return account


def test_onboarding_crea_express_una_vez(world,monkeypatch):
    monkeypatch.setattr(settings,'stripe_secret_key','sk_test_unit_only');monkeypatch.setattr(settings,'stripe_connect_enabled',True)
    calls=[]
    def fake(method,path,data=None,key=None,**kwargs):
        calls.append((path,data))
        return {'id':'acct_test_0','charges_enabled':False,'payouts_enabled':False,'details_submitted':False} if path=='accounts' else {'url':'https://connect.stripe.com/setup/unit','expires_at':int(time.time())+300}
    monkeypatch.setattr(gateways,'stripe_request',fake)
    for _ in range(2):
        response=world.client.post('/api/v1/tenant/payments/stripe-account/onboarding',headers=world.headers(world.admins[0]));assert response.status_code==200,response.text
    assert len([p for p,_ in calls if p=='accounts'])==1 and calls[0][1]['type']=='express'


def test_account_updated_actualiza_estado(world,monkeypatch):
    account=activate(world);account.charges_enabled=False;account.status='pending';world.db.commit()
    monkeypatch.setattr(settings,'stripe_connect_webhook_secret','whsec_unit_only')
    response=post_event(world,{'id':'evt_unit_account','type':'account.updated','account':'acct_test_0','data':{'object':{'id':'acct_test_0','charges_enabled':True,'payouts_enabled':True,'details_submitted':True}}},'connect')
    assert response.status_code==200 and account.status=='active'


def test_checkout_sin_cuenta_activa_no_cobra(world):
    order=pending_order(world)
    response=world.client.post(f'/api/v1/commerce/orders/{order.id}/checkout',headers=world.headers(world.customers[0]))
    assert response.status_code==409 and response.json()['error']['code']=='card_payments_unavailable',response.text


def test_checkout_cobra_cuenta_correcta(world,monkeypatch):
    activate(world,0);activate(world,1);order=pending_order(world)
    calls=[]
    def fake(method,path,data=None,key=None,**kwargs):
        calls.append(kwargs)
        return {'id':'cs_test_unit','url':'https://checkout.stripe.com/c/pay/unit'}
    monkeypatch.setattr(gateways,'stripe_request',fake)
    response=world.client.post(f'/api/v1/commerce/orders/{order.id}/checkout',headers=world.headers(world.customers[0]))
    assert response.status_code==200,response.text
    assert calls and calls[0]['stripe_account']=='acct_test_0'
    assert order.stripe_account_id == 'acct_test_0'


def test_connect_confirma_solo_pedido_de_su_cuenta(world,monkeypatch):
    activate(world);order=pending_order(world);order.stripe_session_id='cs_test_unit';order.stripe_account_id='acct_test_0';world.db.commit()
    monkeypatch.setattr(settings,'stripe_connect_webhook_secret','whsec_unit_only')
    event={'id':'evt_unit_order','type':'checkout.session.completed','account':'acct_test_0','data':{'object':{'id':'cs_test_unit','mode':'payment','payment_status':'paid','currency':'bob','amount_total':15000,'client_reference_id':str(order.id),'payment_intent':'pi_test_unit'}}}
    response=post_event(world,event,'connect')
    assert response.status_code==200 and order.payment_status=='paid',response.text
    order.payment_status='pending';order.status='pending_payment';world.db.commit()
    event['id']='evt_unit_wrong';event['account']='acct_other'
    response=post_event(world,event,'connect')
    assert response.status_code==200 and order.payment_status=='pending'


def test_estado_enmascara_cuenta_y_no_revela_secreto(world):
    activate(world)
    response=world.client.get('/api/v1/tenant/payments/stripe-account',headers=world.headers(world.admins[0]))
    assert response.status_code==200,response.text
    assert 'acct_test_0' not in response.text and response.json()['data']['account_ref'].startswith('acct_')



def test_carrito_ofrece_tarjeta_solo_para_empresa_configurada(world, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_unit_only")
    monkeypatch.setattr(settings, "stripe_connect_enabled", True)
    activate(world, 0)
    for idx, available in [(0, True), (1, False)]:
        response = world.client.get("/api/v1/commerce/cart", headers=world.headers(world.customers[idx]))
        assert response.status_code == 200, response.text
        assert response.json()["data"]["card_payments_available"] is available



def test_pedido_historico_conserva_cuenta_plataforma_aunque_empresa_conecte(world, monkeypatch):
    activate(world)
    order = pending_order(world)
    order.stripe_session_id = "cs_test_legacy"
    world.db.commit()
    calls = []

    def fake(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {}

    monkeypatch.setattr(gateways, "stripe_request", fake)
    monkeypatch.setattr(CommerceService, "release", lambda *args: None)
    CommerceService(world.db, order.tenant_id).cancel(order)
    assert calls == [("POST", "checkout/sessions/cs_test_legacy/expire", {})]
