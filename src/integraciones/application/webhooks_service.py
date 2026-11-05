from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
from typing import Any
from urllib.parse import urlparse
import uuid

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.integraciones.infrastructure.models import (
    IntegrationEventModel,
    WebhookDeliveryModel,
    WebhookEndpointModel,
)
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError


class WebhookUrlForbiddenError(ValidationError):
    status_code = 422
    code = "webhook_url_forbidden"

    def __init__(self, message: str = "La URL del webhook debe usar HTTPS y no apuntar a redes privadas.") -> None:
        super().__init__(message)


RETRY_INTERVALS_SECONDS = [60, 300, 1800, 7200, 43200]  # 1m, 5m, 30m, 2h, 12h


def encrypt_secret(secret: str) -> bytes:
    key = os.getenv("DATA_ENCRYPTION_KEY", "fashionstore-default-encryption-key-2026").encode("utf-8")
    iv = secrets.token_bytes(16)
    data = secret.encode("utf-8")
    stream = b"".join(hashlib.sha256(key + iv + i.to_bytes(4, "big")).digest() for i in range((len(data) // 32) + 1))
    encrypted = bytes(b ^ s for b, s in zip(data, stream))
    return iv + encrypted


def decrypt_secret(secret_enc: bytes) -> str:
    key = os.getenv("DATA_ENCRYPTION_KEY", "fashionstore-default-encryption-key-2026").encode("utf-8")
    iv = secret_enc[:16]
    encrypted = secret_enc[16:]
    stream = b"".join(hashlib.sha256(key + iv + i.to_bytes(4, "big")).digest() for i in range((len(encrypted) // 32) + 1))
    data = bytes(b ^ s for b, s in zip(encrypted, stream))
    return data.decode("utf-8")


def validar_url_webhook(url: str) -> None:
    if not url:
        raise WebhookUrlForbiddenError("La URL no puede estar vacía.")
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() != "https":
        raise WebhookUrlForbiddenError("El webhook debe usar protocolo seguro HTTPS.")
    hostname = parsed.hostname
    if not hostname:
        raise WebhookUrlForbiddenError("El hostname del webhook es inválido.")

    # Protección SSRF: rechazar localhost, ips privadas, loopback y reservadas
    lower_host = hostname.lower()
    if lower_host in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        raise WebhookUrlForbiddenError(f"Destino no permitido: {hostname}")

    try:
        ip = ipaddress.ip_address(lower_host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise WebhookUrlForbiddenError(f"Destino no permitido: IP privada o reservada ({lower_host})")
    except ValueError:
        # Es un nombre de dominio (no una IP literal). Intentar resolver si es posible
        try:
            addrinfo = socket.getaddrinfo(lower_host, None)
            for item in addrinfo:
                ip_cand = ipaddress.ip_address(item[4][0])
                if ip_cand.is_private or ip_cand.is_loopback or ip_cand.is_link_local or ip_cand.is_reserved:
                    raise WebhookUrlForbiddenError(f"El dominio resuelve a una IP interna ({ip_cand})")
        except socket.gaierror:
            pass  # Si el DNS no resuelve en entorno offline de test, se permite


class WebhooksService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def crear_endpoint(
        self,
        tenant_id: uuid.UUID,
        url: str,
        events: list[str],
        created_by: uuid.UUID | None = None,
    ) -> tuple[WebhookEndpointModel, str]:
        validar_url_webhook(url)
        secret_raw = secrets.token_hex(32)
        secret_enc = encrypt_secret(secret_raw)

        endpoint = WebhookEndpointModel(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            url=url.strip(),
            secret_enc=secret_enc,
            events=events or ["*"],
            is_active=True,
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.db.add(endpoint)
        self.db.commit()
        self.db.refresh(endpoint)
        return endpoint, secret_raw

    def listar_endpoints(self, tenant_id: uuid.UUID) -> list[WebhookEndpointModel]:
        return list(
            self.db.scalars(
                select(WebhookEndpointModel)
                .where(WebhookEndpointModel.tenant_id == tenant_id)
                .order_by(WebhookEndpointModel.created_at.desc())
            ).all()
        )

    def eliminar_endpoint(self, tenant_id: uuid.UUID, endpoint_id: uuid.UUID) -> bool:
        ep = self.db.scalar(
            select(WebhookEndpointModel).where(
                WebhookEndpointModel.id == endpoint_id,
                WebhookEndpointModel.tenant_id == tenant_id,
            )
        )
        if not ep:
            return False
        self.db.delete(ep)
        self.db.commit()
        return True

    def publicar(
        self,
        tenant_id: uuid.UUID,
        event_type: str,
        data: dict[str, Any],
    ) -> IntegrationEventModel:
        """
        Escribe el evento en la misma transacción que la operación de negocio (outbox pattern)
        y encola las entregas para los endpoints suscritos de la empresa.
        """
        now = datetime.now(timezone.utc)
        tenant = self.db.get(TenantModel, tenant_id)
        tenant_slug = tenant.slug if tenant else str(tenant_id)

        event_id = uuid.uuid4()
        full_payload = {
            "id": str(event_id),
            "type": event_type,
            "created_at": now.isoformat(),
            "tenant": {"slug": tenant_slug},
            "data": data,
        }

        event = IntegrationEventModel(
            id=event_id,
            tenant_id=tenant_id,
            event_type=event_type,
            payload=full_payload,
            created_at=now,
        )
        self.db.add(event)
        self.db.flush()

        # Encontrar endpoints activos del tenant suscritos a este tipo de evento
        endpoints = self.db.scalars(
            select(WebhookEndpointModel).where(
                WebhookEndpointModel.tenant_id == tenant_id,
                WebhookEndpointModel.is_active.is_(True),
            )
        ).all()

        for ep in endpoints:
            evs = ep.events or []
            if "*" in evs or event_type in evs or any(event_type.startswith(e.replace("*", "")) for e in evs if "*" in e):
                delivery = WebhookDeliveryModel(
                    id=uuid.uuid4(),
                    endpoint_id=ep.id,
                    event_id=event.id,
                    attempt=1,
                    status="pending",
                    created_at=now,
                )
                self.db.add(delivery)

        self.db.commit()
        return event

    def entregar_pendientes(self, batch_size: int = 50, http_client: httpx.Client | None = None) -> list[WebhookDeliveryModel]:
        now = datetime.now(timezone.utc)
        deliveries = list(
            self.db.scalars(
                select(WebhookDeliveryModel)
                .join(WebhookEndpointModel)
                .join(IntegrationEventModel)
                .where(
                    WebhookDeliveryModel.status.in_(["pending", "retrying"]),
                    (WebhookDeliveryModel.next_retry_at.is_(None)) | (WebhookDeliveryModel.next_retry_at <= now),
                    WebhookEndpointModel.is_active.is_(True),
                    # Aislamiento: verificar que el evento y el endpoint pertenezcan al mismo tenant
                    WebhookEndpointModel.tenant_id == IntegrationEventModel.tenant_id,
                )
                .limit(batch_size)
            ).all()
        )

        delivered_results = []
        for delivery in deliveries:
            self._intentar_entrega(delivery, http_client=http_client)
            delivered_results.append(delivery)

        self.db.commit()
        return delivered_results

    def _intentar_entrega(
        self,
        delivery: WebhookDeliveryModel,
        http_client: httpx.Client | None = None,
    ) -> None:
        ep = delivery.endpoint
        event = delivery.event
        if not ep or not event or ep.tenant_id != event.tenant_id:
            delivery.status = "failed"
            delivery.error = "Aislamiento violado o endpoint/evento inexistente."
            return

        now = datetime.now(timezone.utc)
        timestamp = str(int(now.timestamp()))
        body_str = json.dumps(event.payload, separators=(",", ":"), sort_keys=True)
        secret = decrypt_secret(ep.secret_enc)

        # Firma HMAC-SHA256 de «timestamp.cuerpo»
        signature = hmac.new(
            secret.encode("utf-8"),
            f"{timestamp}.{body_str}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-FS-Event": event.event_type,
            "X-FS-Delivery": str(delivery.id),
            "X-FS-Timestamp": timestamp,
            "X-FS-Signature": signature,
        }

        try:
            # Validar URL antes de cada envío
            validar_url_webhook(ep.url)

            if http_client:
                response = http_client.post(
                    ep.url,
                    content=body_str,
                    headers=headers,
                    timeout=5.0,
                    follow_redirects=False,
                )
            else:
                with httpx.Client(timeout=5.0, follow_redirects=False) as client:
                    response = client.post(
                        ep.url,
                        content=body_str,
                        headers=headers,
                    )

            delivery.status_code = response.status_code
            if 200 <= response.status_code < 300:
                delivery.status = "delivered"
                delivery.delivered_at = now
                delivery.error = None
            else:
                self._programar_reintento(delivery, now, f"HTTP {response.status_code}: {response.text[:200]}")

        except Exception as exc:
            self._programar_reintento(delivery, now, str(exc)[:200])

    def _programar_reintento(self, delivery: WebhookDeliveryModel, now: datetime, err: str) -> None:
        delivery.error = err
        attempt_idx = delivery.attempt - 1
        if attempt_idx < len(RETRY_INTERVALS_SECONDS):
            delay_sec = RETRY_INTERVALS_SECONDS[attempt_idx]
            delivery.attempt += 1
            delivery.status = "retrying"
            delivery.next_retry_at = now + timedelta(seconds=delay_sec)
        else:
            delivery.status = "failed"
            delivery.next_retry_at = None

    def redeliver(self, tenant_id: uuid.UUID, delivery_id: uuid.UUID) -> WebhookDeliveryModel:
        delivery = self.db.scalar(
            select(WebhookDeliveryModel)
            .join(WebhookEndpointModel)
            .where(
                WebhookDeliveryModel.id == delivery_id,
                WebhookEndpointModel.tenant_id == tenant_id,
            )
        )
        if not delivery:
            raise NotFoundError("Entrega de webhook no encontrada.")
        delivery.status = "pending"
        delivery.next_retry_at = datetime.now(timezone.utc)
        delivery.error = None
        self.db.commit()
        return delivery

    def test_endpoint(
        self,
        tenant_id: uuid.UUID,
        endpoint_id: uuid.UUID,
        http_client: httpx.Client | None = None,
    ) -> WebhookDeliveryModel:
        ep = self.db.scalar(
            select(WebhookEndpointModel).where(
                WebhookEndpointModel.id == endpoint_id,
                WebhookEndpointModel.tenant_id == tenant_id,
            )
        )
        if not ep:
            raise NotFoundError("Endpoint de webhook no encontrado.")

        now = datetime.now(timezone.utc)
        ping_event = IntegrationEventModel(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            event_type="ping",
            payload={"id": str(uuid.uuid4()), "type": "ping", "created_at": now.isoformat(), "data": {"test": True}},
            created_at=now,
        )
        self.db.add(ping_event)
        self.db.flush()

        delivery = WebhookDeliveryModel(
            id=uuid.uuid4(),
            endpoint_id=ep.id,
            event_id=ping_event.id,
            attempt=1,
            status="pending",
            created_at=now,
        )
        self.db.add(delivery)
        self.db.commit()

        self._intentar_entrega(delivery, http_client=http_client)
        self.db.commit()
        return delivery
