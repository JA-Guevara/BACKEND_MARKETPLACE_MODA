from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import select
from src.operacion_offline.infrastructure.models.sync import SyncConflictModel,SyncOperationModel
from src.ventas_pagos.infrastructure.models import StockModel


def conflict(w):
    stock=w.db.scalar(select(StockModel).where(StockModel.variant_id==w.variant_a.id))
    stock.quantity=0;w.db.commit()
    request_id=uuid4()
    body={'client_version':'qa','device_id':'refund-qa','operations':[{'client_request_id':str(request_id),'type':'SALE',
      'branch_id':str(w.branch_a.id),'device_id':'refund-qa','client_created_at':datetime.now(timezone.utc).isoformat(),
      'payload':{'user_id':str(w.admin_a.id),'cash_point_id':str(w.cash_point_a.id),'payment_method':'cash',
        'subtotal':'150.00','total':'150.00','cash_received':'150.00',
        'items':[{'variant_id':str(w.variant_a.id),'quantity':1,'unit_price':'150.00','regular_price':'150.00'}]}}]}
    result=w.client.post('/api/v1/sync/batch',headers=w.headers(w.admin_a),json=body)
    assert result.status_code==200,result.text
    operation=result.json()['data']['results'][0]
    assert operation['status']=='CONFLICT',operation
    return operation['conflict_id'],str(request_id)


def test_cancelled_offline_sale_requires_online_cash_refund_confirmation(world):
    w=world;cid,op_id=conflict(w)
    resolved=w.client.post(f'/api/v1/sync/conflicts/{cid}/resolve',headers=w.headers(w.admin_a),
        json={'action':'CANCEL','note':'La última prenda ya fue vendida en otra caja.'})
    assert resolved.status_code==200,resolved.text
    assert resolved.json()['data']['refund']['status']=='pending'
    assert resolved.json()['data']['refund']['amount']=='150.00'
    pending=w.client.get('/api/v1/sync/conflicts?status=RESOLVED&refund_status=pending',headers=w.headers(w.admin_a))
    assert pending.json()['data']['total']==1
    status=w.client.post('/api/v1/sync/status',headers=w.headers(w.admin_a),json={'client_request_ids':[op_id]}).json()['data'][0]
    assert status['status']=='REJECTED' and status['refund_status']=='pending' and status['refund_amount']=='150.00'
    data={'request_id':str(uuid4()),'amount':'150.00','reference':'Caja central · recibo R-102'}
    endpoint=f'/api/v1/sync/conflicts/{cid}/refund'
    assert w.client.post(endpoint,headers=w.headers(w.admin_b),json=data).status_code==404
    assert w.client.post(endpoint,headers=w.headers(w.customer_a),json=data).status_code==403
    assert w.client.post(endpoint,headers=w.headers(w.admin_a),json={**data,'amount':'140.00'}).status_code==422
    confirmed=w.client.post(endpoint,headers=w.headers(w.admin_a),json=data)
    assert confirmed.status_code==200,confirmed.text
    assert confirmed.json()['data']['refund']['status']=='confirmed'
    assert w.client.post(endpoint,headers=w.headers(w.admin_a),json=data).status_code==200
    assert w.client.post(endpoint,headers=w.headers(w.admin_a),json={**data,'request_id':str(uuid4())}).status_code==409
    assert w.client.get('/api/v1/sync/conflicts?status=RESOLVED&refund_status=pending',headers=w.headers(w.admin_a)).json()['data']['total']==0
    status=w.client.post('/api/v1/sync/status',headers=w.headers(w.admin_a),json={'client_request_ids':[op_id]}).json()['data'][0]
    assert status['refund_status']=='confirmed'
    assert w.db.scalar(select(StockModel.quantity).where(StockModel.variant_id==w.variant_a.id))==0
