from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import uuid
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
import httpx

from src.infrastructure.database.base import Base
from src.auth.infrastructure.persistence.models.user import UserModel
from src.roles.infrastructure.persistence.models.role import RoleModel
from src.integraciones.application.webhooks_service import (
    RETRY_INTERVALS_SECONDS,
    WebhookUrlForbiddenError,
    WebhooksService,
    decrypt_secret,
    validar_url_webhook,
)
from src.integraciones.infrastructure.models import (
    IntegrationEventModel,
    WebhookDeliveryModel,
    WebhookEndpointModel,
)
from src.plataforma_saas.infrastructure.models.tenant import TenantModel


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    return session


def make_tenant(db: Session, slug: str, name: str = "Empresa") -> TenantModel:
    t = TenantModel(
        id=uuid.uuid4(),
        slug=slug,
        legal_name=f"{name} SRL",
        trade_name=name,
        tax_id=f"NIT-{uuid.uuid4().hex[:8]}",
        contact_email=f"{slug}@example.com",
        status="ACTIVA",
    )
    db.add(t)
    db.commit()
    return t


def test_url_http_o_ip_privada_rechazada() -> None:
    # HTTP en vez de HTTPS
    with pytest.raises(WebhookUrlForbiddenError):
        validar_url_webhook("http://api.ejemplo.com/webhook")

    # Localhost / loopback
    with pytest.raises(WebhookUrlForbiddenError):
        validar_url_webhook("https://localhost/webhook")
    with pytest.raises(WebhookUrlForbiddenError):
        validar_url_webhook("https://127.0.0.1:8443/webhook")

    # IPs privadas
    with pytest.raises(WebhookUrlForbiddenError):
        validar_url_webhook("https://192.168.1.50/webhook")
    with pytest.raises(WebhookUrlForbiddenError):
        validar_url_webhook("https://10.0.0.5/webhook")
    with pytest.raises(WebhookUrlForbiddenError):
        validar_url_webhook("https://172.16.0.1/webhook")

    # URL pública HTTPS válida
    validar_url_webhook("https://api.externa.com/webhooks/fashionstore")


def test_firma_verificable_con_el_secreto() -> None:
    db = make_session()
    tenant = make_tenant(db, "empresa-a", "Empresa A")
    tenant_id = tenant.id

    service = WebhooksService(db)
    ep, raw_secret = service.crear_endpoint(
        tenant_id=tenant_id,
        url="https://api.externa.com/webhooks",
        events=["sale.confirmed"],
    )

    # Publicar un evento de venta
    event = service.publicar(
        tenant_id=tenant_id,
        event_type="sale.confirmed",
        data={"order_id": "ORD-1234", "total": 450.0},
    )

    intercepted_requests = []

    def mock_transport(request: httpx.Request) -> httpx.Response:
        intercepted_requests.append(request)
        return httpx.Response(200, json={"received": True})

    client = httpx.Client(transport=httpx.MockTransport(mock_transport))
    deliveries = service.entregar_pendientes(http_client=client)

    assert len(deliveries) == 1
    assert deliveries[0].status == "delivered"
    assert deliveries[0].status_code == 200

    # Verificar la petición interceptada
    assert len(intercepted_requests) == 1
    req = intercepted_requests[0]
    headers = req.headers
    assert headers["X-FS-Event"] == "sale.confirmed"
    assert "X-FS-Delivery" in headers
    assert "X-FS-Timestamp" in headers
    assert "X-FS-Signature" in headers

    # Verificar que el receptor puede validar la firma HMAC con el secreto
    ts = headers["X-FS-Timestamp"]
    body = req.content.decode("utf-8")
    expected_sig = hmac.new(
        raw_secret.encode("utf-8"),
        f"{ts}.{body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert headers["X-FS-Signature"] == expected_sig


def test_reintentos_con_espera_creciente() -> None:
    db = make_session()
    tenant = make_tenant(db, "empresa-reintento", "Reintento")
    tenant_id = tenant.id

    service = WebhooksService(db)
    ep, _ = service.crear_endpoint(
        tenant_id=tenant_id,
        url="https://api.externa.com/fallo",
        events=["stock.low"],
    )

    event = service.publicar(tenant_id, "stock.low", {"sku": "V-123", "stock": 2})

    # Simular fallo HTTP 500
    def mock_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client = httpx.Client(transport=httpx.MockTransport(mock_error))

    # Intento 1 (debe pasar a retrying y programar reintento a 60s)
    service.entregar_pendientes(http_client=client)
    delivery = db.scalar(select(WebhookDeliveryModel))
    assert delivery.status == "retrying"
    assert delivery.attempt == 2
    assert delivery.next_retry_at is not None

    # Simular que el tiempo avanza para el intento 2
    delivery.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    # Intento 2 (debe programar a 300s / 5m)
    service.entregar_pendientes(http_client=client)
    db.refresh(delivery)
    assert delivery.status == "retrying"
    assert delivery.attempt == 3

    # Simular agotamiento de todos los reintentos
    delivery.attempt = len(RETRY_INTERVALS_SECONDS) + 1
    delivery.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    service.entregar_pendientes(http_client=client)
    db.refresh(delivery)
    assert delivery.status == "failed"
    assert delivery.next_retry_at is None


def test_evento_de_a_nunca_va_a_endpoint_de_b() -> None:
    db = make_session()
    tenant_a = make_tenant(db, "empresa-a", "Empresa A").id
    tenant_b = make_tenant(db, "empresa-b", "Empresa B").id

    service = WebhooksService(db)
    ep_a, _ = service.crear_endpoint(tenant_a, "https://api.a.com/hook", ["*"])
    ep_b, _ = service.crear_endpoint(tenant_b, "https://api.b.com/hook", ["*"])

    # Publicar evento exclusivo de Tenant A
    event_a = service.publicar(tenant_a, "order.paid", {"order_id": "A-001"})

    # Entregas generadas en outbox
    deliveries_a = list(db.scalars(select(WebhookDeliveryModel).where(WebhookDeliveryModel.endpoint_id == ep_a.id)).all())
    deliveries_b = list(db.scalars(select(WebhookDeliveryModel).where(WebhookDeliveryModel.endpoint_id == ep_b.id)).all())

    assert len(deliveries_a) == 1
    assert deliveries_a[0].event_id == event_a.id
    assert len(deliveries_b) == 0  # El endpoint de B jamás recibe entregas de A
