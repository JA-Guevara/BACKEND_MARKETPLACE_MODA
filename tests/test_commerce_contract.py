"""Real HTTP routes, disposable SQLite, no payment network calls."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'frontend_marketplace_moda' / 'scripts'))
from qa_backend import app, ADMIN_EMAIL, CLIENT_EMAIL, PASSWORD
from fastapi.testclient import TestClient
from src.ventas_pagos.infrastructure import gateways

def test_purchase_stock_permissions_and_payment(monkeypatch):
    client = TestClient(app)
    def login(email):
        return {'Authorization': 'Bearer '+client.post('/api/v1/auth/login',json={'email':email,'password':PASSWORD}).json()['data']['access_token']}
    admin, customer = login(ADMIN_EMAIL), login(CLIENT_EMAIL)
    def call(method, path, body=None, auth=customer, status=200):
        result = client.request(method, '/api/v1'+path, json=body, headers=auth)
        assert result.status_code == status, result.text
        return result.json().get('data')
    branch = call('GET','/commerce/branches')[0]['id']
    stock = call('GET',f'/commerce/admin/stock?branch_id={branch}',auth=admin)
    variant = stock[0]['variant_id']
    call('GET',f'/commerce/admin/stock?branch_id={branch}',status=403)
    call('PUT',f'/commerce/admin/stock/{variant}',{'branch_id':branch,'quantity':5},auth=admin)
    call('PUT',f'/commerce/cart/items/{variant}',{'quantity':0},status=422)
    call('PUT',f'/commerce/cart/items/{variant}',{'quantity':2})
    cart = call('GET',f'/commerce/cart?branch_id={branch}')
    assert cart['items'][0]['available'] == 5
    payload = {'branch_id':branch,'address':{'recipient':'Cliente QA','phone':'70001234','line1':'Calle pruebas 123','city':'Santa Cruz','country':'BO'},'payment_method':'manual'}
    order = call('POST','/commerce/orders',payload,status=201)
    assert order['total'] == cart['total']
    assert call('GET','/commerce/cart')['items'] == []
    oid = order['id']
    call('GET',f'/commerce/orders/{oid}',auth=admin,status=404)
    call('PATCH',f'/commerce/admin/orders/{oid}/tracking',{'status':'shipped','carrier':'QA','tracking_number':'QA1'},auth=admin,status=409)
    paid = call('POST',f'/commerce/admin/orders/{oid}/payment',{'method':'transfer','reference':'QA-001'},auth=admin)
    assert paid['payment_status'] == 'paid'
    call('POST',f'/commerce/admin/orders/{oid}/payment',{'method':'cash','reference':'QA-002'},auth=admin,status=409)
    call('PATCH',f'/commerce/admin/orders/{oid}/tracking',{'status':'processing'},auth=admin)
    call('PATCH',f'/commerce/admin/orders/{oid}/tracking',{'status':'shipped'},auth=admin,status=422)
    call('PATCH',f'/commerce/admin/orders/{oid}/tracking',{'status':'shipped','carrier':'QA','tracking_number':'TRACK-1'},auth=admin)
    delivered = call('PATCH',f'/commerce/admin/orders/{oid}/tracking',{'status':'delivered'},auth=admin)
    assert len(delivered['tracking']) == 5
    call('POST',f'/commerce/orders/{oid}/cancel',status=409)
    call('PUT',f'/commerce/cart/items/{variant}',{'quantity':4})
    call('POST','/commerce/orders',payload,status=409)
    assert call('GET','/commerce/cart')['items'][0]['quantity'] == 4
    call('PUT',f'/commerce/cart/items/{variant}',{'quantity':1})
    cancelled = call('POST','/commerce/orders',payload,status=201)
    call('POST',f"/commerce/orders/{cancelled['id']}/cancel")
    call('POST',f"/commerce/orders/{cancelled['id']}/cancel",status=409)
    assert call('GET',f'/commerce/admin/stock?branch_id={branch}',auth=admin)[0]['quantity'] == 3
    call('PUT',f'/commerce/cart/items/{variant}',{'quantity':1})
    stripe_order = call('POST','/commerce/orders',{**payload,'payment_method':'stripe'},status=201)
    sid = stripe_order['id']
    call('POST',f'/commerce/orders/{sid}/checkout',status=503)
    monkeypatch.setattr(gateways,'create_session',lambda order: {'id':'cs_test_local','url':'https://checkout.stripe.com/test-local'})
    call('POST',f'/commerce/orders/{sid}/checkout')
    event = {'id':'evt_local','type':'checkout.session.completed','data':{'object':{'id':'cs_test_local','payment_status':'paid','currency':stripe_order['currency'],'amount_total':int(float(stripe_order['total'])*100),'client_reference_id':sid,'payment_intent':'pi_test'}}}
    from src.ventas_pagos.web import router
    monkeypatch.setattr(router,'verify_event',lambda body,signature:event)
    assert client.post('/api/v1/commerce/stripe/webhook',content=b'{}').status_code == 200
    assert client.post('/api/v1/commerce/stripe/webhook',content=b'{}').json()['duplicate'] is True
    assert call('GET',f'/commerce/orders/{sid}')['payment_status'] == 'paid'
    stats = call('GET','/analytics/dashboard',auth=admin)
    assert stats['paid_orders'] == 2
    assert call('POST','/analytics/insights',auth=admin)['available'] is False
    call('GET','/analytics/dashboard',status=403)
    call('PUT',f'/commerce/cart/items/{variant}',{'quantity':1})
    call('POST',f"/catalog/admin/products/{stock[0]['product_id']}/deactivate",auth=admin)
    unavailable = call('GET',f'/commerce/cart?branch_id={branch}')
    assert unavailable['items'][0]['available'] == 0
    call('POST','/commerce/orders',payload,status=404)
    call('DELETE',f'/commerce/cart/items/{variant}')
    assert call('GET','/commerce/cart')['items'] == []

def test_invalid_webhook_signature():
    from src.infrastructure.config.settings import settings
    from fastapi import HTTPException
    import pytest
    previous = settings.stripe_webhook_secret
    settings.stripe_webhook_secret = 'whsec_local_only'
    try:
        with pytest.raises(HTTPException) as error:
            gateways.verify_event(b'{}','t=1,v1=bad')
        assert error.value.status_code == 400
    finally:
        settings.stripe_webhook_secret = previous
