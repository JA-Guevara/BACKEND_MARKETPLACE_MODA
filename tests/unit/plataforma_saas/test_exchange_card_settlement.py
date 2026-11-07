from src.infrastructure.config.settings import settings
from src.ventas_pagos.infrastructure import gateways
from src.ventas_pagos.web.schemas import ReturnResolution
from tests.unit.plataforma_saas.test_purchase_lifecycle import change_world
from tests.unit.plataforma_saas.test_stripe_connect import activate
from tests.unit.plataforma_saas.test_stripe_billing import post_event


def payment_session(request,paid=False):
    return {'id':'cs_difference','mode':'payment','livemode':False,'currency':'bob','amount_total':3000,
        'client_reference_id':str(request.id),'payment_intent':'pi_difference',
        'status':'complete' if paid else 'open','payment_status':'paid' if paid else 'unpaid'}


def test_signed_connect_webhook_settles_only_the_matching_company(world,monkeypatch):
    w=world;service,request,order,stock=change_world(w)
    request.stripe_session_id='cs_difference';request.stripe_account_id='acct_test_0';w.db.commit()
    monkeypatch.setattr(settings,'stripe_connect_webhook_secret','whsec_unit_only')
    event={'id':'evt_difference_other','type':'checkout.session.completed','account':'acct_other',
           'data':{'object':payment_session(request,True)}}
    assert post_event(w,event,'connect').status_code==200
    w.db.refresh(request);assert request.settlement_status=='payment_pending'
    event.update(id='evt_difference_own',account='acct_test_0')
    assert post_event(w,event,'connect').status_code==200
    assert post_event(w,event,'connect').status_code==200
    w.db.refresh(request);assert request.settlement_status=='paid'
    assert request.status=='approved' # The provider never claims clothes were received.
    monkeypatch.setattr(gateways,'retrieve_session',lambda *a,**kw:payment_session(request,True))
    service.resolver(w.admin_a,request,ReturnResolution(status='completed'))
    assert request.status=='completed'


def test_exchange_checkout_charges_only_difference_and_reuses_session(world,monkeypatch):
    w=world;_,request,order,_=change_world(w);activate(w)
    monkeypatch.setattr(settings,'stripe_connect_enabled',True)
    monkeypatch.setattr(settings,'stripe_secret_key','sk_test_unit_only')
    created=[];paid=False
    def fake(method,path,data=None,key=None,**kwargs):
        if method=='POST':
            created.append((data,key,kwargs));return {'id':'cs_difference','url':'https://checkout.stripe.com/c/pay/unit'}
        return payment_session(request,paid)
    monkeypatch.setattr(gateways,'stripe_request',fake)
    path=f'/api/v1/commerce/returns/{request.id}/checkout'
    for _ in range(2):
        result=w.client.post(path,headers=w.headers(w.customer_a));assert result.status_code==200,result.text
    assert len(created)==1
    data,key,headers=created[0]
    assert data['line_items[0][price_data][unit_amount]']=='3000'
    assert headers['stripe_account']=='acct_test_0'
    assert str(order.id) in data['success_url']
    assert str(request.id) in key
    paid=True
    result=w.client.post(path,headers=w.headers(w.customer_a))
    assert result.status_code==200 and result.json()['data']['url'] is None
    w.db.refresh(request);assert request.settlement_status=='paid'
