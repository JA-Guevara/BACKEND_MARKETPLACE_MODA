"""Stripe test gateway. Raw signed webhook bodies are never trusted before verification."""
import hashlib
import hmac
import json
import time
from decimal import Decimal
import httpx
from fastapi import HTTPException
from src.infrastructure.config.settings import settings


def stripe_request(method: str, path: str, data=None, key=None):
    if not settings.stripe_secret_key.startswith("sk_test_"):
        raise HTTPException(503, "Configure STRIPE_SECRET_KEY de pruebas en el backend.")
    try:
        response = httpx.request(method, "https://api.stripe.com/v1/" + path,
            auth=(settings.stripe_secret_key, ""), data=data,
            headers={"Idempotency-Key": key} if key else {}, timeout=20)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Stripe no esta disponible; vuelva a intentar.") from exc


def create_session(order):
    base = settings.frontend_url.rstrip("/")
    data = {"mode": "payment", "payment_method_types[0]": "card",
        "success_url": base + "/mi-cuenta/pedidos?payment=success",
        "cancel_url": base + "/mi-cuenta/pedidos?payment=cancelled",
        "client_reference_id": str(order.id), "metadata[order_id]": str(order.id),
        "customer_email": order.customer_email}
    for i, item in enumerate(order.items):
        prefix = f"line_items[{i}]"
        data.update({f"{prefix}[price_data][currency]": order.currency,
            f"{prefix}[price_data][product_data][name]": item["name"] + " - " + item["sku"],
            f"{prefix}[price_data][unit_amount]": str(int(Decimal(item["unit_price"]) * 100)),
            f"{prefix}[quantity]": str(item["quantity"])})
    return stripe_request("POST", "checkout/sessions", data, "fashion-order-" + str(order.id))


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
