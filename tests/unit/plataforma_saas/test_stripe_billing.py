import hashlib
import hmac
import json
import time
import pytest
from datetime import datetime, timezone
from sqlalchemy import select, func
from src.infrastructure.config.settings import settings
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel, SubscriptionInvoiceModel
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.ventas_pagos.infrastructure import gateways


def grant_billing(w):
    permission = PermissionModel(code='billing.manage', name='Cobrar plan', module='billing', scope='tenant', is_active=True)
    w.admin_role.permissions.append(permission)
    w.db.commit()


def signed_event(event, secret='whsec_unit_only'):
    body = json.dumps(dict(livemode=False, **event)).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), timestamp.encode()+b'.'+body, hashlib.sha256).hexdigest()
    return body, 't='+timestamp+',v1='+signature


def post_event(w, event, path='billing'):
    body, signature = signed_event(event)
    return w.client.post('/api/v1/stripe/'+path+'/webhook', content=body, headers={'Stripe-Signature': signature, 'Content-Type':'application/json'})


def setup_customer(w):
    w.tenants[0].stripe_customer_id = 'cus_test_a'
    sub = w.db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id == w.tenants[0].id))
    sub.stripe_subscription_id = 'sub_test_a'
    w.db.commit()
    return sub


def test_checkout_sin_configuracion(world, monkeypatch):
    grant_billing(world)
    monkeypatch.setattr(settings, 'stripe_secret_key', '')
    response = world.client.post('/api/v1/tenant/billing/checkout', json={'plan_code':'BASICO','interval':'month'},headers=world.headers(world.admins[0]))
    assert response.status_code == 503 and response.json()['error']['code']=='billing_not_configured'


def test_checkout_usa_precio_y_metadata_de_empresa(world, monkeypatch):
    grant_billing(world); monkeypatch.setattr(settings,'stripe_secret_key','sk_test_unit_only')
    world.plans[0].stripe_price_id_month='price_test_basic'; world.db.commit()
    calls=[]
    def fake(method,path,data=None,key=None,**kwargs):
        calls.append((path,data))
        return {'id':'cus_test_a'} if path=='customers' else {'id':'cs_test_unit','url':'https://checkout.stripe.com/c/pay/unit','expires_at':int(time.time())+1800}
    monkeypatch.setattr(gateways,'stripe_request',fake)
    response=world.client.post('/api/v1/tenant/billing/checkout',json={'plan_code':world.plans[0].code,'interval':'month'},headers=world.headers(world.admins[0]))
    assert response.status_code==200,response.text
    checkout=next(data for path,data in calls if path=='checkout/sessions')
    assert checkout['mode']=='subscription' and checkout['line_items[0][price]']=='price_test_basic'
    assert checkout['subscription_data[metadata][tenant_id]']==str(world.tenants[0].id)
    assert world.tenants[1].stripe_customer_id is None


def test_webhook_firma_invalida_no_escribe(world,monkeypatch):
    monkeypatch.setattr(settings,'stripe_billing_webhook_secret','whsec_unit_only')
    response=world.client.post('/api/v1/stripe/billing/webhook',content=b'{}',headers={'Stripe-Signature':'t=1,v1=invalida'})
    assert response.status_code==400 and response.json()['error']['code']=='stripe_signature_invalid'


def test_invoice_paid_es_idempotente_y_no_toca_empresa_b(world,monkeypatch):
    monkeypatch.setattr(settings,'stripe_billing_webhook_secret','whsec_unit_only')
    sub=setup_customer(world)
    event={'id':'evt_unit_paid','type':'invoice.paid','data':{'object':{'id':'in_test_a','customer':'cus_test_a','subscription':'sub_test_a','currency':'bob','amount_paid':15000,'period_start':int(time.time()),'period_end':int(time.time())+2592000}}}
    before=world.db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id==world.tenants[1].id)).end_date
    first=post_event(world,event);second=post_event(world,event)
    assert first.status_code==second.status_code==200,(first.text,second.text)
    invoices=world.db.scalars(select(SubscriptionInvoiceModel).where(SubscriptionInvoiceModel.tenant_id==world.tenants[0].id)).all()
    assert len(invoices)==1 and invoices[0].status=='paid' and sub.status=='ACTIVA'
    assert world.db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id==world.tenants[1].id)).end_date==before


def test_pago_fallido_no_reactiva(world,monkeypatch):
    monkeypatch.setattr(settings,'stripe_billing_webhook_secret','whsec_unit_only')
    sub=setup_customer(world);sub.status='SOLO_LECTURA';world.db.commit()
    response=post_event(world,{'id':'evt_unit_failed','type':'invoice.payment_failed','data':{'object':{'customer':'cus_test_a','subscription':'sub_test_a'}}})
    assert response.status_code==200 and sub.status=='SOLO_LECTURA'


def test_cambio_precio_actualiza_plan_solo_empresa_correcta(world,monkeypatch):
    monkeypatch.setattr(settings,'stripe_billing_webhook_secret','whsec_unit_only')
    sub=setup_customer(world);world.plans[1].stripe_price_id_month='price_test_pro';world.db.commit()
    response=post_event(world,{'id':'evt_unit_plan','type':'customer.subscription.updated','data':{'object':{'id':'sub_test_a','customer':'cus_test_a','status':'active','items':{'data':[{'price':{'id':'price_test_pro'}}]}}}})
    assert response.status_code==200 and sub.plan_id==world.plans[1].id


def test_portal_sin_cliente(world,monkeypatch):
    grant_billing(world);monkeypatch.setattr(settings,'stripe_secret_key','sk_test_unit_only')
    response=world.client.post('/api/v1/tenant/billing/portal',headers=world.headers(world.admins[0]))
    assert response.status_code==409 and response.json()['error']['code']=='billing_customer_missing'


def test_usuario_sin_permiso_no_puede_iniciar_checkout(world):
    response=world.client.post('/api/v1/tenant/billing/checkout',json={'plan_code':'BASICO','interval':'month'},headers=world.headers(world.customers[0]))
    assert response.status_code==403


def test_listado_planes_es_para_empresa_sin_revelar_ids_stripe(world):
    response=world.client.get('/api/v1/tenant/billing/plans',headers=world.headers(world.admins[0]))
    assert response.status_code==200,response.text
    assert response.json()['data'] and 'stripe_price_id_month' not in response.text



def test_suscripcion_activa_pide_usar_portal_en_vez_de_cobrar_de_nuevo(world, monkeypatch):
    grant_billing(world)
    setup_customer(world)
    world.plans[0].stripe_price_id_month = "price_test_basic"
    world.db.commit()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_unit_only")
    monkeypatch.setattr(gateways, "stripe_request", lambda *args, **kwargs: pytest.fail("No debe abrir otro Checkout"))
    response = world.client.post("/api/v1/tenant/billing/checkout",
                                 json={"plan_code": world.plans[0].code, "interval": "month"},
                                 headers=world.headers(world.admins[0]))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "billing_use_portal"


def test_factura_basil_puede_llegar_antes_de_checkout_y_registra_monto(world, monkeypatch):
    monkeypatch.setattr(settings, "stripe_billing_webhook_secret", "whsec_unit_only")
    subscription = setup_customer(world)
    subscription.stripe_subscription_id = None
    world.plans[1].stripe_price_id_month = "price_test_pro"
    world.db.commit()
    start = int(time.time())
    response = post_event(world, {"id": "evt_invoice_basil", "type": "invoice.paid", "data": {"object": {
        "id": "in_basil", "customer": "cus_test_a", "currency": "bob", "amount_paid": 12750,
        "parent": {"subscription_details": {"subscription": "sub_test_a",
                                           "metadata": {"tenant_id": str(world.tenants[0].id)}}},
        "lines": {"data": [{"pricing": {"price_details": {"price": "price_test_pro"}},
                            "period": {"start": start, "end": start + 2592000}}]},
    }}})
    assert response.status_code == 200, response.text
    assert subscription.stripe_subscription_id == "sub_test_a"
    assert subscription.plan_id == world.plans[1].id
    receipt = world.db.scalar(select(SubscriptionInvoiceModel).where(SubscriptionInvoiceModel.paid_reference == "stripe:in_basil"))
    assert receipt is not None and receipt.status == "paid"
    assert str(receipt.amount) == "127.50"
