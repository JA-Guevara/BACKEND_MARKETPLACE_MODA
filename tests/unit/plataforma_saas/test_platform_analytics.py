from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
from io import BytesIO
from uuid import uuid4
import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel,SubscriptionInvoiceModel


def seed_payments(w):
    sub=w.db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id==w.tenant_a.id))
    now=datetime.now(timezone.utc)
    for index in range(8):
        day=now-timedelta(days=index+1)
        w.db.add(SubscriptionInvoiceModel(id=uuid4(),tenant_id=w.tenant_a.id,subscription_id=sub.id,
            number='TEST-'+str(index),period_start=day.date(),period_end=(day+timedelta(days=30)).date(),amount=Decimal('100.00'),currency='BOB',
            status='paid',issued_at=day-timedelta(days=2),due_at=day,paid_at=day,created_by=w.platform.id))
    w.db.commit()


def test_platform_figures_forecast_and_tenant_permission_boundary(world):
    w=world;seed_payments(w)
    response=w.client.get('/api/v1/platform/analytics',headers=w.headers(w.platform))
    assert response.status_code==200,response.text
    data=response.json()['data']
    assert data['kpis']['collected']=='800.00'
    assert data['kpis']['paid_invoices']==8
    assert data['projection']['available']
    assert len(data['projection']['points'])==14
    assert sum(Decimal(point['value']) for point in data['daily_collections'])==800
    assert w.client.get('/api/v1/platform/analytics',headers=w.headers(w.admin_a)).status_code==403
    filtered=w.client.get('/api/v1/platform/analytics?plan_code=PROFESIONAL',headers=w.headers(w.platform)).json()['data']
    assert filtered['kpis']['collected']=='0.00'
    assert not filtered['projection']['available']
    assert len(filtered['companies'])==1


@pytest.mark.parametrize('format',['xlsx','csv','pdf'])
def test_export_uses_same_filters_and_produces_real_files(world,format):
    w=world;seed_payments(w)
    response=w.client.get('/api/v1/platform/analytics/export?format='+format+'&plan_code=BASICO',headers=w.headers(w.platform))
    assert response.status_code==200,response.text
    if format=='xlsx':
        workbook=load_workbook(BytesIO(response.content))
        assert workbook['Empresas'].max_row==4
        assert workbook['Empresas']['A4'].value=='Moda A'
        assert len(workbook['Cobros y tendencia']._charts)==1
    elif format=='pdf': assert response.content.startswith(b'%PDF')
    else:
        text=response.content.decode('utf-8-sig')
        assert 'Moda A' in text and 'Moda B' not in text
