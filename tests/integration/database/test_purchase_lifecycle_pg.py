from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from sqlalchemy import select,func
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.ventas_pagos.infrastructure.models import OrderModel,StockModel
from tests.integration.database.test_sync_concurrencia_pg import saas_world  # noqa:F401


def test_concurrent_reservation_conversion_creates_one_order(saas_world):
    w=saas_world
    stock=w.db.scalar(select(StockModel).where(StockModel.variant_id==w.variant_a.id))
    stock.quantity=0
    reservation=ReservationModel(tenant_id=w.tenant_a.id,user_id=w.customer_a.id,branch_id=w.branch_a.id,
        status='ready',scheduled_at=datetime.now(timezone.utc),inventory_held=True,
        items=[{'variant_id':str(w.variant_a.id),'quantity':1}],tracking=[])
    w.db.add(reservation);w.db.commit()
    headers=w.headers(w.customer_a)
    def convert():return w.client.post(f'/api/v1/reservations/{reservation.id}/order',headers=headers,json={})
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:convert(),range(2)))
    assert [r.status_code for r in results]==[200,200],[r.text for r in results]
    assert results[0].json()['data']['id']==results[1].json()['data']['id']
    w.db.expire_all()
    assert w.db.scalar(select(func.count()).select_from(OrderModel))==1
    assert w.db.get(StockModel,stock.id).quantity==0


def test_last_garment_online_and_offline_reservation_compete_safely(saas_world):
    w=saas_world;stock=w.db.scalar(select(StockModel).where(StockModel.variant_id==w.variant_a.id))
    stock.quantity=1;w.db.commit()
    from uuid import uuid4
    now=datetime.now(timezone.utc)
    sale={'client_version':'qa','device_id':'last-piece','operations':[{'client_request_id':str(uuid4()),'type':'SALE',
      'branch_id':str(w.branch_a.id),'device_id':'last-piece','client_created_at':now.isoformat(),
      'payload':{'user_id':str(w.admin_a.id),'cash_point_id':str(w.cash_point_a.id),'payment_method':'cash',
        'subtotal':'150.00','total':'150.00','items':[{'variant_id':str(w.variant_a.id),'quantity':1,'unit_price':'150.00','regular_price':'150.00'}]}}]}
    reserve={'branch_id':str(w.branch_a.id),'scheduled_at':(now+timedelta(days=1)).isoformat(),
             'items':[{'variant_id':str(w.variant_a.id),'quantity':1}],'client_key':str(uuid4())}
    def sell():return w.client.post('/api/v1/sync/batch',headers=w.headers(w.admin_a),json=sale)
    def hold():return w.client.post('/api/v1/reservations',headers=w.headers(w.customer_a),json=reserve)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(sell);b=pool.submit(hold);sold,held=a.result(),b.result()
    assert sold.status_code==200,sold.text
    sale_status=sold.json()['data']['results'][0]['status']
    assert (sale_status=='CONFIRMED' and held.status_code==409) or (sale_status=='CONFLICT' and held.status_code==201),(sold.text,held.text)
    w.db.expire_all()
    assert w.db.get(StockModel,stock.id).quantity==0
