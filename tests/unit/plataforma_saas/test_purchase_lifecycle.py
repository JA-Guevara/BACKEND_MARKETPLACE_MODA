from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.usuarios_catalogo.infrastructure.models.catalog import ProductVariantModel, SizeModel
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel, OrderReturnModel
from src.ventas_pagos.application.returns_service import ReturnsService
from src.ventas_pagos.application.exchange_settlement import ExchangeSettlement
from src.ventas_pagos.web.schemas import ExchangeRequest, ReturnResolution
from src.shared.exceptions.domain_exception import ConflictError


def reservation(w, quantity=1):
    stock=w.db.scalar(select(StockModel).where(StockModel.variant_id==w.variant_a.id))
    stock.quantity=0
    row=ReservationModel(tenant_id=w.tenant_a.id,user_id=w.customer_a.id,branch_id=w.branch_a.id,
        scheduled_at=datetime.now(timezone.utc),status='ready',inventory_held=True,
        items=[{'variant_id':str(w.variant_a.id),'name':'Vestido','quantity':quantity}],tracking=[])
    w.db.add(row);w.db.commit()
    return row,stock


def test_reservation_last_garment_transfers_hold_and_cancel_releases_once(world):
    w=world;r,stock=reservation(w)
    url=f'/api/v1/reservations/{r.id}/order'
    result=w.client.post(url,headers=w.headers(w.customer_a),json={'payment_method':'manual'})
    assert result.status_code==200,result.text
    order=result.json()['data']
    assert order['total']=='150.00'
    w.db.refresh(stock);assert stock.quantity==0
    w.db.refresh(r);assert r.status=='converted' and not r.inventory_held
    assert str(r.order_id)==order['id']
    assert w.client.post(url,headers=w.headers(w.customer_a),json={'payment_method':'manual'}).json()['data']['id']==order['id']
    assert w.client.post(url,headers=w.headers(w.customer_b),json={}).status_code==404
    assert w.client.post(url,headers=w.headers(w.customer_a),json={'payment_method':'stripe'}).status_code==409
    assert w.client.post(f'/api/v1/reservations/{r.id}/cancel',headers=w.headers(w.customer_a)).status_code==409
    cancelled=w.client.post(f"/api/v1/commerce/orders/{order['id']}/cancel",headers=w.headers(w.customer_a))
    assert cancelled.status_code==200,cancelled.text
    w.db.refresh(stock);assert stock.quantity==1
    assert w.client.post(f"/api/v1/commerce/orders/{order['id']}/cancel",headers=w.headers(w.customer_a)).status_code==409
    w.db.refresh(stock);assert stock.quantity==1


def test_reservation_partial_purchase_releases_declined_quantity(world):
    w=world;r,stock=reservation(w,3)
    result=w.client.post(f'/api/v1/reservations/admin/{r.id}/order',headers=w.headers(w.admin_a),
        json={'items':[{'variant_id':str(w.variant_a.id),'quantity':1}]})
    assert result.status_code==200,result.text
    w.db.refresh(stock);assert stock.quantity==2
    assert result.json()['data']['total']=='150.00'


def test_reservation_order_is_paid_and_collected_without_fake_shipping(world):
    w=world;r,stock=reservation(w)
    order=w.client.post(f'/api/v1/reservations/{r.id}/order',headers=w.headers(w.customer_a),json={}).json()['data']
    path=f"/api/v1/commerce/admin/orders/{order['id']}"
    assert w.client.patch(path+'/tracking',headers=w.headers(w.admin_a),json={'status':'delivered'}).status_code==409
    paid=w.client.post(path+'/payment',headers=w.headers(w.admin_a),json={'method':'cash','reference':'Caja QA-103'})
    assert paid.status_code==200,paid.text
    assert w.client.patch(path+'/tracking',headers=w.headers(w.admin_a),json={'status':'shipped','carrier':'Falso','tracking_number':'Falso'}).status_code==409
    received=w.client.patch(path+'/tracking',headers=w.headers(w.admin_a),json={'status':'delivered'})
    assert received.status_code==200,received.text
    assert not received.json()['data']['carrier'] and received.json()['data']['payment_status']=='paid'
    w.db.refresh(stock);assert stock.quantity==0
    linked=w.client.get(f'/api/v1/reservations/{r.id}',headers=w.headers(w.customer_a)).json()['data']
    assert linked['order_status']=='delivered' and linked['payment_status']=='paid'


def test_shipping_order_keeps_its_shipping_states(world):
    w=world;r,_=reservation(w)
    order=w.client.post(f'/api/v1/reservations/{r.id}/order',headers=w.headers(w.customer_a),json={}).json()['data']
    from uuid import UUID
    saved=w.db.get(OrderModel,UUID(order['id']));saved.address={'recipient':'Cliente','line1':'Domicilio'}
    saved.status='paid';saved.payment_status='paid';w.db.commit()
    path=f"/api/v1/commerce/admin/orders/{order['id']}/tracking"
    assert w.client.patch(path,headers=w.headers(w.admin_a),json={'status':'delivered'}).status_code==409
    assert w.client.patch(path,headers=w.headers(w.admin_a),json={'status':'processing'}).status_code==200
    assert w.client.patch(path,headers=w.headers(w.admin_a),json={'status':'shipped'}).status_code==422


def change_world(w,new_price=180,method='cash',discount=0):
    size=SizeModel(tenant_id=w.tenant_a.id,code='L2',name='L')
    w.db.add(size);w.db.flush()
    replacement=ProductVariantModel(product_id=w.product_a.id,size_id=size.id,color_id=w.color.id,
        sku='EX-'+uuid4().hex[:8],price_override=Decimal(new_price))
    w.db.add(replacement);w.db.flush()
    stock=StockModel(branch_id=w.branch_a.id,variant_id=replacement.id,quantity=1)
    order=OrderModel(tenant_id=w.tenant_a.id,user_id=w.customer_a.id,customer_email=w.customer_a.email,
        branch_id=w.branch_a.id,number='TEST-'+uuid4().hex[:12],status='delivered',payment_status='paid',
        payment_method=method,payment_reference='pi_original' if method=='stripe' else 'caja-1',
        stripe_account_id='acct_original' if method=='stripe' else None,
        total=Decimal(150-discount),subtotal=Decimal(150),discount_total=Decimal(discount),
        paid_at=datetime.now(timezone.utc),items=[{'variant_id':str(w.variant_a.id),'name':'Vestido',
        'quantity':1,'unit_price':'150.00','line_total':'150.00'}],tracking=[])
    w.db.add_all([stock,order]);w.db.commit()
    data=ExchangeRequest(variant_id=w.variant_a.id,replacement_variant_id=replacement.id,
        quantity=1,reason='Necesito otra talla',client_request_id=uuid4())
    service=ReturnsService(w.db,w.tenant_a.id)
    request=service.solicitar_cambio(w.customer_a,order,data)
    service.resolver(w.admin_a,request,ReturnResolution(status='approved'))
    return service,request,order,stock


def test_exchange_extra_charge_must_be_confirmed_and_is_idempotent(world):
    w=world;service,request,order,stock=change_world(w)
    assert request.difference_amount==30 and request.settlement_status=='payment_pending'
    w.db.refresh(stock);assert stock.quantity==0
    with pytest.raises(ConflictError):
        service.resolver(w.admin_a,request,ReturnResolution(status='completed'))
    service.resolver(w.admin_a,request,ReturnResolution(status='completed',settlement_method='cash',
        settlement_amount=30,settlement_reference='Caja-24'))
    assert request.settlement_status=='paid'
    before=w.db.scalar(select(StockModel.quantity).where(StockModel.variant_id==w.variant_a.id))
    service.resolver(w.admin_a,request,ReturnResolution(status='completed'))
    assert w.db.scalar(select(StockModel.quantity).where(StockModel.variant_id==w.variant_a.id))==before
    assert not service.devolvible(order)['can_request']


def test_exchange_refund_uses_net_paid_value_and_original_stripe_account(world,monkeypatch):
    w=world;service,request,order,stock=change_world(w,new_price=90,method='stripe',discount=30)
    assert request.difference_amount==-30 and request.refund_amount==30
    calls=[]
    def refund(original,request,**kwargs):
        calls.append((original.payment_reference,request.refund_amount,kwargs));return 're_refund'
    monkeypatch.setattr('src.ventas_pagos.infrastructure.gateways.refund_order_return',refund)
    service.resolver(w.admin_a,request,ReturnResolution(status='completed'))
    assert request.settlement_status=='refunded'
    assert request.settlement_reference=='re_refund'
    assert calls==[('pi_original',Decimal('30.00'),{'stripe_account':'acct_original'})]


def test_exchange_provider_failure_does_not_complete_or_restore_stock(world,monkeypatch):
    w=world;service,request,order,stock=change_world(w,new_price=90,method='stripe')
    before=w.db.scalar(select(StockModel.quantity).where(StockModel.variant_id==w.variant_a.id))
    def fail(*args,**kwargs):raise ConflictError('Reintegro todavía pendiente.')
    monkeypatch.setattr('src.ventas_pagos.infrastructure.gateways.refund_order_return',fail)
    with pytest.raises(ConflictError):service.resolver(w.admin_a,request,ReturnResolution(status='completed'))
    w.db.refresh(request);assert request.status=='approved' and request.settlement_status=='refund_pending'
    assert w.db.scalar(select(StockModel.quantity).where(StockModel.variant_id==w.variant_a.id))==before
    w.db.refresh(stock);assert stock.quantity==0


def test_exchange_signed_confirmation_checks_account_amount_and_scope(world):
    w=world;_,request,order,_=change_world(w)
    request.stripe_account_id='acct_empresa';request.stripe_session_id='cs_change'
    session={'id':'cs_change','mode':'payment','livemode':False,'client_reference_id':str(request.id),
             'currency':'bob','amount_total':3000,'payment_status':'paid','payment_intent':'pi_difference'}
    settlement=ExchangeSettlement(w.db)
    with pytest.raises(ConflictError):settlement.confirm(request,session,'acct_otra')
    with pytest.raises(ConflictError):settlement.confirm(request,{**session,'amount_total':15000},'acct_empresa')
    assert settlement.confirm(request,session,'acct_empresa')
    assert not settlement.confirm(request,session,'acct_empresa')
    w.db.commit()
    other=w.client.post(f'/api/v1/commerce/returns/{request.id}/checkout',headers=w.headers(w.customer_b))
    assert other.status_code==404
