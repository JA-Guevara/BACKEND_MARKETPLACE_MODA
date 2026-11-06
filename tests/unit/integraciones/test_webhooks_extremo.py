import hashlib,hmac,json
from uuid import uuid4
import httpx
from sqlalchemy import select
from tests.unit.plataforma_saas.conftest import world
from src.integraciones.application.webhooks_service import WebhooksService, encrypt_secret
from src.integraciones.infrastructure.models import IntegrationEventModel, WebhookDeliveryModel, WebhookEndpointModel
from src.plataforma_saas.application.jobs.runner import TareasProgramadas
from src.ventas_pagos.application.service import CommerceService
from src.ventas_pagos.web.schemas import POSSale


def endpoint(w,number=0):
    ep=WebhookEndpointModel(tenant_id=w.tenants[number].id,url='https://hooks.example.com/events',secret_enc=encrypt_secret('unit_only'),events=['sale.confirmed'],is_active=True)
    w.db.add(ep);w.db.commit();return ep


def sell(w):
    data=POSSale(client_request_id=uuid4(),branch_id=w.branches[0].id,cash_point_id=w.cash_points[0].id,customer_name='Cliente Prueba',payment_method='cash',payment_reference='UNIT-001',payment_received=True,items=[{'variant_id':w.variants[0].id,'quantity':1}])
    return CommerceService(w.db,w.tenants[0].id).pos_sale(w.admins[0],data)


def test_pos_encola_evento_una_vez(world):
    endpoint(world);sell(world)
    assert len(world.db.scalars(select(IntegrationEventModel)).all())==1
    assert len(world.db.scalars(select(WebhookDeliveryModel).where(WebhookDeliveryModel.status=='pending')).all())==1


def test_tick_entrega_evento_con_firma(world,monkeypatch):
    endpoint(world);sell(world)
    sent=[]
    def receive(request):
        signature=hmac.new(b'unit_only',request.headers['X-FS-Timestamp'].encode()+b'.'+request.content,hashlib.sha256).hexdigest()
        assert hmac.compare_digest(signature,request.headers['X-FS-Signature'])
        sent.append(json.loads(request.content));return httpx.Response(204)
    client=httpx.Client(transport=httpx.MockTransport(receive))
    monkeypatch.setattr('src.integraciones.application.webhooks_service.validar_url_webhook',lambda _:None)
    original=WebhooksService.entregar_pendientes
    monkeypatch.setattr(WebhooksService,'entregar_pendientes',lambda self:original(self,http_client=client))
    runs=TareasProgramadas(world.db).tick()
    assert any(row.job=='webhooks.deliver' and row.status=='ok' for row in runs)
    assert len(sent)==1 and sent[0]['type']=='sale.confirmed'


def test_sin_suscriptor_no_crea_outbox(world):
    sell(world)
    assert world.db.scalar(select(IntegrationEventModel)) is None


def test_evento_a_no_encola_para_b(world):
    ep=endpoint(world,1);sell(world)
    assert world.db.scalar(select(WebhookDeliveryModel).where(WebhookDeliveryModel.endpoint_id==ep.id)) is None
