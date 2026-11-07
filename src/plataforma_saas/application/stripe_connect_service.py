"""Stripe Connect: altas Accounts v2 y cargos directos por empresa, solo TEST.

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
from src.infrastructure.database.session import set_rls_context
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

ACCOUNTS_API_VERSION = '2026-10-28.endive'


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


def tarjeta_disponible(db: Session, tenant_id: UUID | None) -> bool:
    if tenant_id is None or not settings.stripe_connect_enabled or not (settings.stripe_secret_key or "").startswith("sk_test_"):
        return False
    account = cuenta_de_empresa(db, tenant_id)
    return bool(account and account.status == "active" and account.charges_enabled)


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
        # Stripe documenta la representación v1 de cuentas v2. Se conserva también
        # la compatibilidad con cuentas históricas y los webhooks account.updated.
        if not settings.stripe_connect_enabled or not (settings.stripe_secret_key or '').startswith('sk_test_'):
            raise BillingNotConfiguredError()
        fresh = gateways.stripe_request('GET', 'accounts/' + account.stripe_account_id)
        if fresh.get('id') != account.stripe_account_id:
            raise ConflictError('Stripe devolvió una cuenta distinta a la conectada.')
        self._cuenta_actualizada(account.stripe_account_id, fresh)
        return {"status": account.status, "charges_enabled": account.charges_enabled,
                "payouts_enabled": account.payouts_enabled, "details_submitted": account.details_submitted,
                "account_ref": enmascarar_cuenta(account.stripe_account_id), "updated_at": account.updated_at}

    # --- E5 · alta Accounts v2 + formulario alojado por Stripe -------------------------------
    def onboarding(self, tenant_id: UUID) -> dict[str, Any]:
        if not settings.stripe_connect_enabled or not (settings.stripe_secret_key or "").startswith("sk_test_"):
            raise BillingNotConfiguredError("Los cobros con tarjeta aún no están habilitados en la plataforma.")
        tenant = self.db.scalar(select(TenantModel).where(TenantModel.id == tenant_id).with_for_update())
        if tenant is None:
            raise NotFoundError("Empresa no encontrada.", code="tenant_not_found")
        account = cuenta_de_empresa(self.db, tenant_id)
        if account is None:
            created = gateways.stripe_request('POST', 'v2/core/accounts', data={
                'display_name': tenant.trade_name,
                'contact_email': tenant.contact_email,
                'identity': {'country': settings.stripe_connect_test_country.lower()},
                'dashboard': 'full',
                'defaults': {'responsibilities': {'fees_collector': 'stripe', 'losses_collector': 'stripe'}},
                'configuration': {'merchant': {'capabilities': {'card_payments': {'requested': True}}}},
                'metadata': {'tenant_id': str(tenant.id)},
            }, key=f'fs-connect-v2-account-{tenant.id}', api_version=ACCOUNTS_API_VERSION)
            if created.get('object') != 'v2.core.account' or created.get('livemode') is not False or not str(created.get('id', '')).startswith('acct_'):
                raise ConflictError('Stripe no devolvió una cuenta válida de prueba.')
            account = TenantPaymentAccountModel(
                tenant_id=tenant.id, stripe_account_id=created["id"],
                charges_enabled=False, payouts_enabled=False, details_submitted=False,
                status='pending',
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
        set_rls_context(self.db, is_platform=True)
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
        if order is None:
            from src.ventas_pagos.application.exchange_settlement import ExchangeSettlement
            ExchangeSettlement(self.db).webhook(cuenta, session)
            return
        if order is None or order.stripe_account_id != cuenta:
            # Evento de otra cuenta conectada: nunca toca pedidos de otra empresa.
            return
        if order.status != "pending_payment" or order.payment_status == "paid":
            return
        service = CommerceService(self.db)
        service.confirm_stripe_payment(order, session, "Pago confirmado por webhook firmado de Stripe Connect.")
        service.audit(order, "stripe_event", "Pago con tarjeta confirmado en la cuenta Stripe de la empresa.")
        self.pedidos_confirmados.append(order)
