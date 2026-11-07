"""Solo QA local: empresas sintéticas y SQLite temporal; no conecta a producción."""
from pathlib import Path
import runpy
import uvicorn
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy.orm import sessionmaker

backend=Path(__file__).resolve().parents[2]
fixture=runpy.run_path(str(backend/'tests/e2e/offline_server.py'))
world=fixture['world']
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.infrastructure.config.settings import settings
from src.plataforma_saas.application.tenant_backup_service import process_backups
from tests.unit.plataforma_saas.test_platform_analytics import seed_payments
settings.tenant_backup_encryption_key=SecretStr(Fernet.generate_key().decode())
for code,role,scope in [('platform.ops.read',world.platform_role,'platform'),('platform.ops.write',world.platform_role,'platform'),('tenant.data_export',world.admin_role,'tenant')]:
    role.permissions.append(PermissionModel(code=code,name=code,module='users',scope=scope))
world.db.commit()
seed_payments(world)
from datetime import datetime,timezone
from decimal import Decimal
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.ventas_pagos.infrastructure.models import OrderModel,StockModel
from src.usuarios_catalogo.infrastructure.models.catalog import SizeModel,ProductVariantModel
from sqlalchemy import select
reservation=ReservationModel(tenant_id=world.tenant_a.id,user_id=world.customer_a.id,branch_id=world.branch_a.id,
    scheduled_at=datetime.now(timezone.utc),status='ready',inventory_held=True,items=[{'variant_id':str(world.variant_a.id),'name':'Vestido Demo','quantity':1}],tracking=[])
order=OrderModel(tenant_id=world.tenant_a.id,user_id=world.customer_a.id,customer_email=world.customer_a.email,
    number='QA-CAMBIO-001',branch_id=world.branch_a.id,status='delivered',payment_status='paid',payment_method='cash',
    total=Decimal(150),subtotal=Decimal(150),paid_at=datetime.now(timezone.utc),items=[{'variant_id':str(world.variant_a.id),
    'name':'Vestido Demo','quantity':1,'unit_price':'150.00','line_total':'150.00','size':'M','color':'Negro'}],tracking=[])
size=SizeModel(tenant_id=world.tenant_a.id,code='L-QA',name='L')
world.db.add_all([reservation,order,size]);world.db.flush()
replacement=ProductVariantModel(product_id=world.product_a.id,size_id=size.id,color_id=world.color.id,sku='SKU-CAMBIO-QA',price_override=Decimal(180))
world.db.add(replacement);world.db.flush();world.db.add(StockModel(branch_id=world.branch_a.id,variant_id=replacement.id,quantity=2))
world.db.scalar(select(StockModel).where(StockModel.variant_id==world.variant_a.id)).quantity=18
world.db.commit()
@world.app.get('/qa/ids')
def ids():return {'tenant_a':str(world.tenant_a.id),'tenant_b':str(world.tenant_b.id),'reservation':str(reservation.id),'order':str(order.id),'replacement':str(replacement.id)}
@world.app.post('/qa/process')
def process():return {'processed':process_backups(sessionmaker(bind=fixture['engine'],expire_on_commit=False))}
try:uvicorn.run(world.app,host='127.0.0.1',port=57519,log_level='error')
finally:
    world.client.close();world.db.close();fixture['engine'].dispose();fixture['database_file'].unlink(missing_ok=True)
