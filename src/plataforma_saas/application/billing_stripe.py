"""Servicio de facturación e integración con Stripe Billing en modo prueba (opcional).

Permite:
- Apertura del Customer Portal de Stripe para autogestión de pagos.
- Procesamiento de webhooks invoice.paid y customer.subscription.updated.
- Verificación criptográfica HMAC-SHA256 con STRIPE_BILLING_WEBHOOK_SECRET.
- La ruta simulada de pagos sigue siendo la principal del prototipo.
"""
import hashlib
import hmac
import os
import time
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.plataforma_saas.application.billing_service import BillingService
from src.plataforma_saas.application.jobs.suscripciones import CicloSuscripcion
from src.plataforma_saas.infrastructure.models.subscription import (
    SubscriptionInvoiceModel,
    SubscriptionModel,
)
from src.shared.exceptions.domain_exception import DomainValidationError


class StripeBilling:
    def __init__(self, db: Session):
        self.db = db
        self.webhook_secret = os.getenv("STRIPE_BILLING_WEBHOOK_SECRET")
        self.stripe_key = os.getenv("STRIPE_SECRET_KEY")

    def verificar_firma(self, payload: bytes | str, sig_header: str | None) -> bool:
        """Verifica la firma HMAC-SHA256 enviada por Stripe en Stripe-Signature."""
        if not self.webhook_secret or not sig_header:
            return False

        if isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        else:
            payload_bytes = payload

        # Formato de cabecera Stripe: t=1492774577,v1=5257a869e7ecebeda32affa62cd490b135c7425172ecb2e6d93a08f44e69813f
        items = dict(item.split("=", 1) for item in sig_header.split(",") if "=" in item)
        timestamp = items.get("t")
        expected_sig = items.get("v1")

        if not timestamp or not expected_sig:
            return False

        # Prevenir ataques de repetición (tolerancia de 5 minutos)
        try:
            t = int(timestamp)
            if abs(time.time() - t) > 300:
                return False
        except ValueError:
            return False

        signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
        computed = hmac.new(
            self.webhook_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(computed, expected_sig)

    def crear_customer_portal_session(self, tenant_id: UUID, return_url: str) -> dict[str, str]:
        """Crea una sesión de Customer Portal en modo prueba para autogestión de métodos de pago."""
        # En modo prueba sin cliente real de Stripe, emite una URL segura de portal de prueba
        session_id = f"test_portal_{uuid4().hex[:16]}"
        portal_url = f"https://billing.stripe.com/p/session/{session_id}?return_url={return_url}"
        return {
            "url": portal_url,
            "session_id": session_id,
            "tenant_id": str(tenant_id),
        }

    def procesar_webhook(
        self,
        event: dict[str, Any],
        sig_header: str | None = None,
        raw_body: bytes | None = None,
    ) -> dict[str, Any]:
        """Procesa eventos de webhook de Stripe (invoice.paid y customer.subscription.updated)."""
        # Si se configuró STRIPE_BILLING_WEBHOOK_SECRET, la firma es obligatoria
        if self.webhook_secret and raw_body is not None:
            if not self.verificar_firma(raw_body, sig_header):
                raise DomainValidationError("Firma de webhook de Stripe inválida.", code="stripe_signature_invalid")

        event_type = event.get("type", "")
        event_id = event.get("id", str(uuid4()))
        data_object = event.get("data", {}).get("object", {})

        if event_type == "invoice.paid":
            return self._manejar_invoice_paid(data_object, event_id)
        elif event_type == "customer.subscription.updated":
            return self._manejar_subscription_updated(data_object, event_id)

        return {"handled": False, "event_type": event_type, "message": "Evento ignorado"}

    def _manejar_invoice_paid(self, invoice_data: dict[str, Any], event_id: str) -> dict[str, Any]:
        """Concilia un comprobante pagado a través de Stripe y reactiva el ciclo de suscripción."""
        stripe_invoice_id = invoice_data.get("id", "")
        # Extraer ID interno de la factura desde metadata o número
        metadata = invoice_data.get("metadata", {})
        invoice_uuid_str = metadata.get("internal_invoice_id")
        invoice_number = metadata.get("invoice_number") or invoice_data.get("number")

        invoice = None
        if invoice_uuid_str:
            try:
                invoice = self.db.get(SubscriptionInvoiceModel, UUID(invoice_uuid_str))
            except ValueError:
                pass

        if not invoice and invoice_number:
            stmt = select(SubscriptionInvoiceModel).where(SubscriptionInvoiceModel.number == invoice_number)
            invoice = self.db.scalars(stmt).first()

        if not invoice:
            return {
                "handled": True,
                "action": "invoice.paid",
                "matched": False,
                "message": f"Comprobante no encontrado para factura Stripe {stripe_invoice_id}",
            }

        ref = f"stripe_{stripe_invoice_id or event_id}"
        billing_service = BillingService(self.db)
        updated_invoice = billing_service.registrar_pago(invoice.id, referencia=ref)

        return {
            "handled": True,
            "action": "invoice.paid",
            "matched": True,
            "invoice_id": str(updated_invoice.id),
            "reference": ref,
        }

    def _manejar_subscription_updated(self, sub_data: dict[str, Any], event_id: str) -> dict[str, Any]:
        """Sincroniza el estado de la suscripción reportado por Stripe."""
        status = sub_data.get("status", "")
        metadata = sub_data.get("metadata", {})
        sub_uuid_str = metadata.get("internal_subscription_id")

        if not sub_uuid_str:
            return {
                "handled": True,
                "action": "customer.subscription.updated",
                "matched": False,
                "message": "Suscripción sin metadata interna",
            }

        try:
            sub = self.db.get(SubscriptionModel, UUID(sub_uuid_str))
        except ValueError:
            sub = None

        if not sub:
            return {
                "handled": True,
                "action": "customer.subscription.updated",
                "matched": False,
                "message": f"Suscripción interna {sub_uuid_str} no encontrada",
            }

        if status in ("active", "trialing"):
            CicloSuscripcion(self.db).reactivar(sub)

        return {
            "handled": True,
            "action": "customer.subscription.updated",
            "matched": True,
            "status": status,
            "subscription_id": str(sub.id),
        }
