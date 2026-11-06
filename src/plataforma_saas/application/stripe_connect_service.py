"""Stripe Connect: cada empresa cobra sus ventas con su propia cuenta Express (PS-PX O1.6).

RN-ST1: la plataforma solo guarda el id de la cuenta conectada y su estado; nunca
claves de la empresa. RN-ST2: la tarjeta se ofrece solo con charges_enabled.
Cargo directo: cada llamada de un pedido lleva la cabecera Stripe-Account de la
empresa del pedido; jamás la de otra empresa.
"""
from datetime import datetime, timezone
import time
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.infrastructure.config.settings import settings
from src.plataforma_saas.application.billing_stripe import (
    BillingNotConfiguredError,
    leer_evento,
    registrar_evento_una_vez,
    verificar_firma_stripe,
)
from src.plataforma_saas.infrastructure.models.stripe_saas import TenantPaymentAccountModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError
from src.ventas_pagos.infrastructure import gateways


class CardPaymentsUnavailableError(ConflictError):
    status_code = 409
    code = "card_payments_unavailable"

    def __init__(self, message: str = "Esta tienda aún no acepta pagos con tarjeta. Usa QR o transferencia.") -> None:
        super().__init__(message)


def enmascarar_cuenta(account_id: str | None) -> str | None:
    if not account_id:
        return None
    return "acct_…" + account_id[-4:]


def estado_de(charges_enabled: bool, details_submitted: bool) -> str:
    if charges_enabled:
        return "active"
    return "restricted" if details_submitted else "pending"


def cuenta_de_empresa(db: Session, tenant_id: UUID) -> TenantPaymentAccountModel | None:
    return db.get(TenantPaymentAccountModel, tenant_id)


def cuenta_para_cobrar(db: Session, tenant_id: UUID) -> str:
    """Cuenta conectada activa de la empresa del pedido; si no hay, 409 (RN-ST2)."""
    account = cuenta_de_empresa(db, tenant_id)
    if account is None or account.status != "active" or not account.charges_enabled:
        raise CardPaymentsUnavailableError()
    return account.stripe_account_id


def cuenta_del_pedido(db: Session, order) -> str | None:
    """Cuenta en la que vive el cobro de un pedido ya iniciado (consulta, expiración, reembolso).
    No exige charges_enabled: un pago hecho sigue en esa cuenta aunque luego se restrinja."""
    account = cuenta_de_empresa(db, order.tenant_id)
    return account.stripe_account_id if account is not None else None


class StripeConnectService:
    def __init__(self, db: Session):
        self.db = db
        # Pedidos confirmados en este webhook: el router avisa al cliente tras el commit.
        self.pedidos_confirmados: list = []

    # --- E4 · estado -----------------------------------------------------------------------
    def estado(self, tenant_id: UUID) -> dict[str, Any]:
        account = cuenta_de_empresa(self.db, tenant_id)
        if account is None:
            return {"status": "not_connected", "charges_enabled": False, "payouts_enabled": False,
                    "details_submitted": False, "account_ref": None, "updated_at": None}
        return {"status": account.status, "charges_enabled": account.charges_enabled,
                "payouts_enabled": account.payouts_enabled, "details_submitted": account.details_submitted,
                "account_ref": enmascarar_cuenta(account.stripe_account_id), "updated_at": account.updated_at}

    # --- E5 · onboarding Express -----------------------------------------------------------
    def onboarding(self, tenant_id: UUID) -> dict[str, Any]:
        if not settings.stripe_connect_enabled or not (settings.stripe_secret_key or "").startswith("sk_test_"):
            raise BillingNotConfiguredError("Los cobros con tarjeta aún no están habilitados en la plataforma.")
        tenant = self.db.get(TenantModel, tenant_id)
        if tenant is None:
            raise NotFoundError("Empresa no encontrada.", code="tenant_not_found")
        account = cuenta_de_empresa(self.db, tenant_id)
        if account is None:
            created = gateways.stripe_request("POST", "accounts", data={
                "type": "express",
                "email": tenant.contact_email,
                "business_profile[name]": tenant.trade_name,
                "capabilities[card_payments][requested]": "true",
                "capabilities[transfers][requested]": "true",
                "metadata[tenant_id]": str(tenant.id),
            }, key=f"fs-connect-account-{tenant.id}")
            account = TenantPaymentAccountModel(
                tenant_id=tenant.id, stripe_account_id=created["id"],
                charges_enabled=bool(created.get("charges_enabled")),
                payouts_enabled=bool(created.get("payouts_enabled")),
                details_submitted=bool(created.get("details_submitted")),
                status=estado_de(bool(created.get("charges_enabled")), bool(created.get("details_submitted"))),
                updated_at=datetime.now(timezone.utc),
            )
            self.db.add(account)
            self.db.flush()
        base = settings.frontend_url.rstrip("/") + "/admin/empresa/cobros"
        link = gateways.stripe_request("POST", "account_links", data={
            "account": account.stripe_account_id,
            "type": "account_onboarding",
            "refresh_url": base + "?stripe=reintentar",
            "return_url": base + "?stripe=volver",
        })
        try:
            expires = datetime.fromtimestamp(int(link.get("expires_at")), tz=timezone.utc)
        except (TypeError, ValueError):
            expires = datetime.fromtimestamp(time.time() + 300, tz=timezone.utc)
        return {"onboarding_url": link["url"], "expires_at": expires}

    # --- E6 · webhook de Connect -----------------------------------------------------------
    def procesar_webhook(self, raw_body: bytes, sig_header: str | None) -> dict[str, Any]:
        verificar_firma_stripe(raw_body, sig_header, settings.stripe_connect_webhook_secret)
        event = leer_evento(raw_body)
        if not registrar_evento_una_vez(self.db, event, "connect"):
            return {"received": True}
        cuenta = event.get("account")
        obj = (event.get("data") or {}).get("object") or {}
        if not isinstance(cuenta, str) or not cuenta or not isinstance(obj, dict):
            return {"received": True}
        tipo = event.get("type")
        if tipo == "account.updated" and obj.get("id") == cuenta:
            self._cuenta_actualizada(cuenta, obj)
        elif tipo in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
            self._pedido_pagado(cuenta, obj)
        # charge.refunded: el reembolso ya se concilia de forma síncrona en ReturnsService.
        return {"received": True}

    def _cuenta_actualizada(self, cuenta: str, obj: dict[str, Any]) -> None:
        account = self.db.scalar(select(TenantPaymentAccountModel)
                                 .where(TenantPaymentAccountModel.stripe_account_id == cuenta))
        if account is None:
            return
        account.charges_enabled = bool(obj.get("charges_enabled"))
        account.payouts_enabled = bool(obj.get("payouts_enabled"))
        account.details_submitted = bool(obj.get("details_submitted"))
        account.status = estado_de(account.charges_enabled, account.details_submitted)
        account.updated_at = datetime.now(timezone.utc)

    def _pedido_pagado(self, cuenta: str, session: dict[str, Any]) -> None:
        from src.ventas_pagos.application.service import CommerceService
        from src.ventas_pagos.infrastructure.models import OrderModel

        if session.get("mode") != "payment" or session.get("payment_status") != "paid" or not session.get("id"):
            return
        order = self.db.scalar(select(OrderModel).where(OrderModel.stripe_session_id == session["id"]).with_for_update())
        if order is None or cuenta_del_pedido(self.db, order) != cuenta:
            # Evento de otra cuenta conectada: nunca toca pedidos de otra empresa.
            return
        if order.status != "pending_payment" or order.payment_status == "paid":
            return
        service = CommerceService(self.db)
        service.confirm_stripe_payment(order, session, "Pago confirmado por webhook firmado de Stripe Connect.")
        service.audit(order, "stripe_event", "Pago con tarjeta confirmado en la cuenta Stripe de la empresa.")
        self.pedidos_confirmados.append(order)
