"""Online financial settlement; receiving clothing is a separate staff action."""
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select
from src.infrastructure.config.settings import settings

from src.shared.exceptions.domain_exception import ConflictError
from src.ventas_pagos.infrastructure import gateways
from src.ventas_pagos.infrastructure.models import OrderReturnModel


class ExchangeSettlement:
    def __init__(self, db):
        self.db = db

    def checkout(self, request, order, channel='web'):
        if request.status != 'approved' or request.difference_amount <= 0:
            raise ConflictError('Primero debe aprobarse un cambio con diferencia a pagar.')
        self.reconcile(request, commit=False)
        if request.settlement_status == 'paid':
            self.db.commit()
            return {'url': None, 'status': 'paid'}
        if not request.stripe_session_id:
            from src.plataforma_saas.application.stripe_connect_service import cuenta_para_cobrar
            account = cuenta_para_cobrar(self.db, request.tenant_id)
            session = gateways.create_session(SimpleNamespace(
                id=request.id, number='CAMBIO-' + order.number, total=request.difference_amount,
                currency=request.currency, customer_email=order.customer_email, sales_channel=channel,
            ), stripe_account=account, return_order_id=order.id,
                payment_return_url=settings.public_api_url.rstrip('/')+f'/commerce/payment-return/{order.id}' if channel=='mobile' else None,
                idempotency_key=f'fashion-exchange-{request.id}-{request.settlement_attempt or 0}')
            request.stripe_session_id = session['id']
            request.stripe_url = session['url']
            request.stripe_account_id = account
            request.settlement_method = 'stripe'
            self.db.commit()
        # A cancelled browser visit is not evidence that the payment failed.
        return {'url': request.stripe_url, 'status': request.settlement_status}

    def confirm(self, request, session, account):
        if request.stripe_account_id != account:
            raise ConflictError('La cuenta del cobro no coincide con la empresa del cambio.')
        if (session.get('id') != request.stripe_session_id or session.get('mode') != 'payment'
                or session.get('livemode') is not False
                or session.get('client_reference_id') != str(request.id)
                or session.get('currency', '').lower() != request.currency.lower()
                or session.get('amount_total') != int(Decimal(request.difference_amount) * 100)):
            raise ConflictError('La confirmación no coincide con la diferencia del cambio.')
        if session.get('payment_status') != 'paid':
            return False
        intent = session.get('payment_intent')
        intent = intent.get('id') if isinstance(intent, dict) else intent
        if not intent:
            raise ConflictError('El proveedor no devolvió la referencia del cobro.')
        if request.settlement_status in {'paid','refunded'}:
            return False
        if request.status != 'approved':
            raise ConflictError('Este cambio requiere revisión antes de confirmar el cobro.')
        request.settlement_status = 'paid'
        request.settlement_reference = intent
        request.settlement_method = 'stripe'
        return True

    def reconcile(self, request, *, commit=True):
        if request.stripe_session_id and request.settlement_status != 'paid':
            session = gateways.retrieve_session(request.stripe_session_id,
                **gateways.en_cuenta(request.stripe_account_id))
            self.confirm(request, session, request.stripe_account_id)
            if session.get('status') == 'expired' and session.get('payment_status') != 'paid':
                request.stripe_session_id = request.stripe_url = None
                request.settlement_attempt = (request.settlement_attempt or 0)+1
            if commit:
                self.db.commit()
        return request

    def before_reject(self, request):
        if request.stripe_session_id:
            self.reconcile(request, commit=False)
            if request.settlement_status == 'paid':
                payment=SimpleNamespace(id=request.id,payment_reference=request.settlement_reference,currency=request.currency)
                request.refund_amount=request.difference_amount
                request.settlement_reference=gateways.refund_order_return(payment,request,
                    **gateways.en_cuenta(request.stripe_account_id))
                request.settlement_status='refunded'
                return
            if request.stripe_session_id:
                gateways.stripe_request('POST', f'checkout/sessions/{request.stripe_session_id}/expire',
                    **gateways.en_cuenta(request.stripe_account_id))

    def complete(self, request, order, data):
        difference = Decimal(request.difference_amount or 0)
        if difference > 0:
            if request.stripe_session_id:
                # Do not commit the stock transaction while reconciling.
                session = gateways.retrieve_session(request.stripe_session_id,
                    **gateways.en_cuenta(request.stripe_account_id))
                self.confirm(request, session, request.stripe_account_id)
            if request.settlement_status != 'paid':
                if request.stripe_session_id:
                    gateways.stripe_request('POST',f'checkout/sessions/{request.stripe_session_id}/expire',
                        **gateways.en_cuenta(request.stripe_account_id))
                self._cash(request, data, difference)
        elif difference < 0:
            if order.payment_method == 'stripe':
                request.settlement_reference = gateways.refund_order_return(order, request,
                    **gateways.en_cuenta(order.stripe_account_id))
                request.settlement_method = 'stripe'
            else:
                self._cash(request, data, difference)
            request.settlement_status = 'refunded'

    @staticmethod
    def _cash(request, data, difference):
        amount = getattr(data, 'settlement_amount', None)
        reference = (getattr(data, 'settlement_reference', None) or '').strip()
        if (getattr(data, 'settlement_method', None) != 'cash' or amount is None
                or Decimal(amount) != abs(difference) or len(reference) < 3):
            raise ConflictError('Confirmá el cobro o reintegro en efectivo por el importe exacto, con una referencia de caja. Los pagos electrónicos se verifican con el proveedor.')
        request.settlement_method = 'cash'
        request.settlement_reference = reference
        request.settlement_status = 'paid' if difference > 0 else 'refunded'

    def webhook(self, account, session):
        request = self.db.scalar(select(OrderReturnModel).where(
            OrderReturnModel.stripe_session_id == session.get('id'),
            OrderReturnModel.stripe_account_id == account,
        ).with_for_update())
        if request is None:
            return False
        self.confirm(request, session, account)
        return True
