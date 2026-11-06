"""Stripe Billing: la plataforma cobra sus planes (PS-PX O1.5, siempre modo prueba).

- Checkout de suscripción (E1) y portal de facturación (E2) con el cliente de la empresa.
- Webhook firmado (E3) idempotente por id de evento (stripe_events, RN-ST4).
- El estado de la suscripción solo lo cambian estos webhooks o el registro manual
  de la plataforma (RN-ST3); el retorno del navegador nunca activa nada.
- La empresa sale del token (E1/E2) o del cliente/suscripción de Stripe ya
  vinculados a ella (E3); nunca de un parámetro del cliente (RN03).
"""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import time
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.infrastructure.config.settings import settings
from src.infrastructure.database.session import set_rls_context
from src.plataforma_saas.application.billing_service import BillingService
from src.plataforma_saas.application.jobs.suscripciones import CicloSuscripcion
from src.plataforma_saas.infrastructure.models.plan import PlanModel
from src.plataforma_saas.infrastructure.models.stripe_saas import StripeEventModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.shared.exceptions.base_exception import AppException
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError, ValidationError
from src.ventas_pagos.infrastructure import gateways

FIRMA_TOLERANCIA_S = 300


class BillingNotConfiguredError(AppException):
    status_code = 503
    code = "billing_not_configured"

    def __init__(self, message: str = "El cobro con tarjeta no está configurado. Usa el pago manual.") -> None:
        super().__init__(message)


class PlanNotAvailableError(ValidationError):
    status_code = 422
    code = "plan_not_available"

    def __init__(self, message: str = "Este plan no está disponible para pago con tarjeta. Usa el pago manual.") -> None:
        super().__init__(message)


class BillingCustomerMissingError(ConflictError):
    status_code = 409
    code = "billing_customer_missing"

    def __init__(self, message: str = "Primero paga un plan con tarjeta.") -> None:
        super().__init__(message)


class StripeSignatureInvalidError(AppException):
    status_code = 400
    code = "stripe_signature_invalid"

    def __init__(self, message: str = "Firma de webhook de Stripe inválida.") -> None:
        super().__init__(message)


def verificar_firma_stripe(raw_body: bytes, sig_header: str | None, secret: str, ahora: float | None = None) -> None:
    """Valida Stripe-Signature (t=…,v1=…) con HMAC-SHA256 y tolerancia de 5 min; si no, 400."""
    if not secret or not sig_header:
        raise StripeSignatureInvalidError()
    timestamp, firmas = None, []
    for item in sig_header.split(","):
        key, _, value = item.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            firmas.append(value)
    try:
        t = int(timestamp or "")
    except ValueError:
        raise StripeSignatureInvalidError() from None
    if not firmas or abs((ahora if ahora is not None else time.time()) - t) > FIRMA_TOLERANCIA_S:
        raise StripeSignatureInvalidError()
    esperada = hmac.new(secret.encode(), f"{t}.".encode() + raw_body, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(esperada, firma) for firma in firmas):
        raise StripeSignatureInvalidError()


def leer_evento(raw_body: bytes) -> dict[str, Any]:
    try:
        event = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError):
        raise StripeSignatureInvalidError() from None
    if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not event["id"]:
        raise StripeSignatureInvalidError()
    if event.get("livemode") is True:
        # Este plan solo opera en modo prueba: un evento live nunca cambia estado.
        raise StripeSignatureInvalidError("Evento live rechazado: Stripe opera en modo prueba.")
    return event


def registrar_evento_una_vez(db: Session, event: dict[str, Any], source: str) -> bool:
    """True si el evento es nuevo; False si ya se procesó (RN-ST4). Misma transacción que sus efectos."""
    if db.get(StripeEventModel, event["id"]) is not None:
        return False
    try:
        with db.begin_nested():
            db.add(StripeEventModel(event_id=event["id"], type=str(event.get("type", ""))[:100],
                                    source=source, processed_at=datetime.now(timezone.utc)))
    except IntegrityError:
        return False
    return True


def _stripe_configurado() -> bool:
    return (settings.stripe_secret_key or "").strip().startswith("sk_test_")


def _dt(epoch: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


class StripeBilling:
    def __init__(self, db: Session):
        self.db = db

    # --- E13 · planes que la empresa puede elegir -------------------------------------------
    def planes_disponibles(self) -> list[dict[str, Any]]:
        plans = self.db.scalars(select(PlanModel).where(PlanModel.is_active.is_(True))
                                .order_by(PlanModel.reference_price, PlanModel.code)).all()
        return [{"code": p.code, "name": p.name, "reference_price": f"{p.reference_price:.2f}",
                 "stripe_ready": bool(p.stripe_price_id_month)} for p in plans]

    # --- E7 · la plataforma vincula el precio mensual de Stripe -----------------------------
    def vincular_precio(self, plan_id: UUID, price_id: str | None) -> dict[str, Any]:
        plan = self.db.get(PlanModel, plan_id)
        if plan is None:
            raise NotFoundError("Plan no encontrado.", code="plan_not_found")
        plan.stripe_price_id_month = price_id
        self.db.flush()
        return {"plan_id": plan.id, "code": plan.code, "stripe_price_id_month": plan.stripe_price_id_month,
                "stripe_ready": bool(plan.stripe_price_id_month)}

    # --- E1 · Checkout de suscripción -------------------------------------------------------
    def crear_checkout(self, tenant_id: UUID, plan_code: str) -> dict[str, Any]:
        if not _stripe_configurado():
            raise BillingNotConfiguredError()
        plan = self.db.scalar(select(PlanModel).where(PlanModel.code == plan_code))
        if plan is None or not plan.is_active or not plan.stripe_price_id_month:
            raise PlanNotAvailableError()
        tenant = self.db.scalar(select(TenantModel).where(TenantModel.id == tenant_id).with_for_update())
        if tenant is None:
            raise NotFoundError("Empresa no encontrada.", code="tenant_not_found")
        subscription = self._suscripcion_actual(tenant_id)
        if subscription is not None and subscription.stripe_subscription_id:
            raise ConflictError("Gestiona el plan de tu suscripción existente desde el portal de Stripe.",
                                code="billing_use_portal")
        existing_customer = bool(tenant.stripe_customer_id)
        customer = self._asegurar_cliente(tenant)
        if existing_customer:
            subscriptions = gateways.stripe_request("GET", f"subscriptions?customer={customer}&status=all&limit=100")
            if any(row.get("status") in {"active", "trialing", "past_due", "unpaid", "paused", "incomplete"}
                   for row in subscriptions.get("data", [])):
                raise ConflictError("Gestiona el plan de tu suscripción existente desde el portal de Stripe.",
                                    code="billing_use_portal")
            pending = gateways.stripe_request("GET", f"checkout/sessions?customer={customer}&status=open&limit=20")
            for session in pending.get("data", []):
                if session.get("mode") != "subscription":
                    continue
                expires = _dt(session.get("expires_at"))
                if expires is not None and expires > datetime.now(timezone.utc):
                    if (session.get("metadata") or {}).get("plan_code") == plan.code and session.get("url"):
                        return {"checkout_url": session["url"], "expires_at": expires}
                    raise ConflictError("Hay un pago de suscripción pendiente. Complétalo o espera a que caduque.",
                                        code="billing_checkout_pending")
        base = settings.frontend_url.rstrip("/") + "/admin/empresa/suscripcion"
        session = gateways.stripe_request("POST", "checkout/sessions", data={
            "mode": "subscription",
            "customer": customer,
            "client_reference_id": str(tenant.id),
            "line_items[0][price]": plan.stripe_price_id_month,
            "line_items[0][quantity]": 1,
            "metadata[tenant_id]": str(tenant.id),
            "metadata[plan_code]": plan.code,
            "subscription_data[metadata][tenant_id]": str(tenant.id),
            "success_url": base + "?pago=ok",
            "cancel_url": base + "?pago=cancelado",
        })
        expires = _dt(session.get("expires_at")) or datetime.fromtimestamp(time.time() + 1800, tz=timezone.utc)
        return {"checkout_url": session["url"], "expires_at": expires}

    def _asegurar_cliente(self, tenant: TenantModel) -> str:
        if tenant.stripe_customer_id:
            return tenant.stripe_customer_id
        customer = gateways.stripe_request("POST", "customers", data={
            "name": tenant.trade_name,
            "email": tenant.contact_email,
            "metadata[tenant_id]": str(tenant.id),
        }, key=f"fs-billing-customer-{tenant.id}")
        tenant.stripe_customer_id = customer["id"]
        self.db.flush()
        return tenant.stripe_customer_id

    # --- E2 · portal de facturación ---------------------------------------------------------
    def crear_portal(self, tenant_id: UUID) -> dict[str, str]:
        if not _stripe_configurado():
            raise BillingNotConfiguredError()
        tenant = self.db.get(TenantModel, tenant_id)
        if tenant is None or not tenant.stripe_customer_id:
            raise BillingCustomerMissingError()
        session = gateways.stripe_request("POST", "billing_portal/sessions", data={
            "customer": tenant.stripe_customer_id,
            "return_url": settings.frontend_url.rstrip("/") + "/admin/empresa/suscripcion",
        })
        return {"portal_url": session["url"]}

    # --- E3 · webhook -----------------------------------------------------------------------
    def procesar_webhook(self, raw_body: bytes, sig_header: str | None) -> dict[str, Any]:
        verificar_firma_stripe(raw_body, sig_header, settings.stripe_billing_webhook_secret)
        event = leer_evento(raw_body)
        set_rls_context(self.db, is_platform=True)
        if not registrar_evento_una_vez(self.db, event, "billing"):
            return {"received": True}
        obj = (event.get("data") or {}).get("object") or {}
        handler = {
            "checkout.session.completed": self._checkout_completado,
            "invoice.paid": self._factura_pagada,
            "invoice.payment_failed": self._pago_fallido,
            "customer.subscription.updated": self._suscripcion_actualizada,
            "customer.subscription.deleted": self._suscripcion_eliminada,
        }.get(event.get("type", ""))
        if handler is not None and isinstance(obj, dict):
            handler(obj)
        self.db.flush()
        return {"received": True}

    def _tenant_por_cliente(self, customer: Any) -> TenantModel | None:
        if not isinstance(customer, str) or not customer:
            return None
        return self.db.scalar(select(TenantModel).where(TenantModel.stripe_customer_id == customer))

    def _suscripcion_actual(self, tenant_id: UUID) -> SubscriptionModel | None:
        return self.db.scalar(select(SubscriptionModel).where(
            SubscriptionModel.tenant_id == tenant_id, SubscriptionModel.closed_at.is_(None),
        ).order_by(SubscriptionModel.start_date.desc()).limit(1))

    def _suscripcion_de(self, obj: dict[str, Any], sub_field: str) -> SubscriptionModel | None:
        """Suscripción interna solo si cliente y suscripción de Stripe pertenecen a la misma empresa."""
        tenant = self._tenant_por_cliente(obj.get("customer"))
        stripe_sub = obj.get(sub_field)
        if tenant is None or not isinstance(stripe_sub, str) or not stripe_sub:
            return None
        sub = self.db.scalar(select(SubscriptionModel).where(SubscriptionModel.stripe_subscription_id == stripe_sub))
        return sub if sub is not None and sub.tenant_id == tenant.id else None

    def _checkout_completado(self, obj: dict[str, Any]) -> None:
        if obj.get("mode") != "subscription":
            return
        tenant = self._tenant_por_cliente(obj.get("customer"))
        stripe_sub = obj.get("subscription")
        if tenant is None or str(obj.get("client_reference_id") or tenant.id) != str(tenant.id):
            return
        sub = self._suscripcion_actual(tenant.id)
        if (sub is not None and isinstance(stripe_sub, str) and stripe_sub
                and sub.stripe_subscription_id in (None, stripe_sub)):
            sub.stripe_subscription_id = stripe_sub

    def _invoice_subscription(self, obj: dict[str, Any], *, allow_initial_link: bool = False) -> SubscriptionModel | None:
        details = (obj.get("parent") or {}).get("subscription_details") or obj.get("subscription_details") or {}
        subscription_id = obj.get("subscription") or details.get("subscription")
        sub = self._suscripcion_de({**obj, "subscription": subscription_id}, "subscription")
        if sub is not None or not allow_initial_link or not isinstance(subscription_id, str) or not subscription_id:
            return sub
        tenant = self._tenant_por_cliente(obj.get("customer"))
        metadata = details.get("metadata") or {}
        if tenant is None or metadata.get("tenant_id") != str(tenant.id):
            return None
        current = self._suscripcion_actual(tenant.id)
        if current is not None and current.stripe_subscription_id is None:
            current.stripe_subscription_id = subscription_id
            return current
        return None

    def _factura_pagada(self, obj: dict[str, Any]) -> None:
        sub = self._invoice_subscription(obj, allow_initial_link=True)
        if sub is None:
            return
        lineas = (obj.get("lines") or {}).get("data") or []
        plan = self._plan_de_lineas(lineas)
        if plan is not None and plan.id != sub.plan_id:
            sub.plan_id = plan.id
        periodo = next((linea["period"] for linea in lineas if isinstance(linea, dict) and linea.get("period")), {})
        period_start = _dt(periodo.get("start")) or _dt(obj.get("period_start"))
        period_end = _dt(periodo.get("end")) or _dt(obj.get("period_end"))
        amount = obj.get("amount_paid")
        currency = obj.get("currency")
        billing = BillingService(self.db)
        invoice = billing.emitir_periodo(
            sub, inicio_periodo=period_start.date() if period_start else None,
            fin_periodo=period_end.date() if period_end else None,
        )
        reference = f"stripe:{obj.get('id') or 'invoice'}"
        if invoice.status == "paid":
            return
        if isinstance(amount, int) and amount >= 0 and isinstance(currency, str) and currency.lower() == "bob":
            invoice.amount = Decimal(amount) / 100
        billing.registrar_pago(invoice.id, referencia=reference)
        if period_end is not None and period_end.date() > sub.end_date:
            sub.end_date = period_end.date()

    def _pago_fallido(self, obj: dict[str, Any]) -> None:
        # El ciclo diario aplica gracia y solo lectura si no se renueva el período.
        sub = self._invoice_subscription(obj)
        if sub is not None:
            CicloSuscripcion(self.db)._publicar_cambio(sub, "payment_failed")

    def _suscripcion_actualizada(self, obj: dict[str, Any]) -> None:
        sub = self._suscripcion_de(obj, "id")
        if sub is None:
            return
        plan = self._plan_de_lineas((obj.get("items") or {}).get("data"))
        if plan is not None and plan.id != sub.plan_id:
            sub.plan_id = plan.id
            CicloSuscripcion(self.db)._publicar_cambio(sub, "plan_changed")

    def _suscripcion_eliminada(self, obj: dict[str, Any]) -> None:
        # Se desvincula el cobro automático; el acceso sigue hasta end_date y luego el ciclo.
        sub = self._suscripcion_de(obj, "id")
        if sub is not None:
            sub.stripe_subscription_id = None
            CicloSuscripcion(self.db)._publicar_cambio(sub, "auto_renew_canceled")

    def _plan_de_lineas(self, lineas: Any) -> PlanModel | None:
        if not isinstance(lineas, list):
            return None
        for linea in lineas:
            if not isinstance(linea, dict):
                continue
            pricing = (linea.get("pricing") or {}).get("price_details") or {}
            price = (linea.get("price") or {}).get("id") or pricing.get("price")
            if isinstance(price, str) and price:
                plan = self.db.scalar(select(PlanModel).where(PlanModel.stripe_price_id_month == price))
                if plan is not None:
                    return plan
        return None

