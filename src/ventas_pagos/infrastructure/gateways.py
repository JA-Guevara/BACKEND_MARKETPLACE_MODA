"""Stripe test gateway. Raw signed webhook bodies are never trusted before verification."""
import hashlib
import hmac
import json
import logging
import time
from decimal import Decimal
import httpx
from fastapi import HTTPException
from src.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)


def stripe_request(method: str, path: str, data=None, key=None):
    if not settings.stripe_secret_key.startswith("sk_test_"):
        raise HTTPException(503, "Configure STRIPE_SECRET_KEY de pruebas en el backend.")
    try:
        response = httpx.request(method, "https://api.stripe.com/v1/" + path,
            auth=(settings.stripe_secret_key, ""), data=data,
            headers={"Idempotency-Key": key} if key else {}, timeout=20)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        # El cliente recibe un mensaje seguro; Railway conserva únicamente el
        # estado HTTP para diagnosticar la configuración sin registrar claves.
        logger.warning("Stripe rechazó la solicitud: metodo=%s ruta=%s estado=%s", method, path, exc.response.status_code)
        raise HTTPException(502, "Stripe no esta disponible; vuelva a intentar.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Stripe no estuvo disponible: metodo=%s ruta=%s causa=%s", method, path, type(exc).__name__)
        raise HTTPException(502, "Stripe no esta disponible; vuelva a intentar.") from exc


def create_session(order):
    base = settings.frontend_url.rstrip("/")
    data = {"mode": "payment", "payment_method_types[0]": "card",
        "success_url": base + "/mi-cuenta/pedidos?payment=success&pedido=" + str(order.id),
        "cancel_url": base + "/mi-cuenta/pedidos?payment=cancelled&pedido=" + str(order.id),
        "client_reference_id": str(order.id), "metadata[order_id]": str(order.id),
        "customer_email": order.customer_email}
    # Stripe debe cobrar el total calculado por el backend, incluidos cupones
    # y promociones. El desglose permanece en nuestro pedido y comprobante.
    data.update({
        "line_items[0][price_data][currency]": order.currency,
        "line_items[0][price_data][product_data][name]": f"Pedido {order.number}",
        "line_items[0][price_data][unit_amount]": str(int(Decimal(order.total) * 100)),
        "line_items[0][quantity]": "1",
    })
    return stripe_request("POST", "checkout/sessions", data, "fashion-order-" + str(order.id))


def retrieve_session(session_id):
    # El ID procede de nuestra base, nunca de una URL o cuerpo del cliente.
    return stripe_request("GET", f"checkout/sessions/{session_id}?expand[]=payment_intent.latest_charge")


def refund_order_return(order, devolucion):
    """Reembolsa una devolución de prueba una sola vez, incluso tras un corte de red."""
    if not order.payment_reference or not order.payment_reference.startswith("pi_"):
        raise HTTPException(409, "El pedido no tiene un pago Stripe verificable para reintegrar.")
    amount = int(Decimal(devolucion.refund_amount) * 100)
    if amount <= 0:
        return None
    intent = order.payment_reference
    existing = stripe_request("GET", f"refunds?payment_intent={intent}&limit=100")
    refund = next((row for row in existing.get("data", [])
                   if row.get("metadata", {}).get("return_id") == str(devolucion.id)), None)
    if refund is None:
        refund = stripe_request("POST", "refunds", {
            "payment_intent": intent, "amount": str(amount),
            "reason": "requested_by_customer",
            "metadata[return_id]": str(devolucion.id),
            "metadata[order_id]": str(order.id),
        }, key=f"fashion-return-{devolucion.id}")
    if (refund.get("payment_intent") != intent or refund.get("amount") != amount
            or refund.get("currency", "").lower() != order.currency.lower()):
        raise HTTPException(502, "Stripe devolvió un reembolso que no coincide con la solicitud.")
    if refund.get("status") != "succeeded":
        raise HTTPException(409, "El reembolso Stripe aún no fue confirmado; volvé a intentarlo más tarde.")
    return refund["id"]


def verify_event(body: bytes, signature: str):
    if not settings.stripe_webhook_secret:
        raise HTTPException(503, "Webhook Stripe no configurado.")
    try:
        parts = [part.split("=", 1) for part in signature.split(",")]
        timestamp = next(value for name, value in parts if name == "t")
        signatures = [value for name, value in parts if name == "v1"]
        if abs(time.time() - int(timestamp)) > 300:
            raise ValueError("Expired signature")
        expected = hmac.new(settings.stripe_webhook_secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, value) for value in signatures):
            raise ValueError("Invalid signature")
        event = json.loads(body)
        if event.get("livemode") is not False:
            raise ValueError("Only test events accepted")
        return event
    except (ValueError, StopIteration, TypeError) as exc:
        raise HTTPException(400, "Firma Stripe invalida.") from exc
