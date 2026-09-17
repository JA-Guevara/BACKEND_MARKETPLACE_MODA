import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.main import create_app
from src.auth.web.dependencies import get_current_user
from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.base import Base
from src.infrastructure.database.session import get_db
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel
from src.ventas_pagos.infrastructure import gateways
from src.ventas_pagos.application.service import CommerceService


@pytest.fixture
def world(monkeypatch):
    engine = create_engine('sqlite+pysqlite:///:memory:', poolclass=StaticPool,
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = UserModel(email='buyer@example.test', password_hash='unused', first_name='Buyer', last_name='Test',
                         is_active=True, is_verified=True)
        db.add(user)
        db.flush()
        order = OrderModel(number='FS-TEST', user_id=user.id, customer_email=user.email, branch_id=uuid.uuid4(),
                           payment_method='stripe', total=Decimal('169'), currency='bob', address={}, items=[],
                           stripe_session_id='cs_test_owned', stripe_url='https://checkout.stripe.com/test', tracking=[])
        db.add(order)
        db.commit()
        result = {'id': order.stripe_session_id, 'livemode': False, 'mode': 'payment', 'status': 'complete',
                  'payment_status': 'paid', 'currency': 'bob', 'amount_total': 16900,
                  'client_reference_id': str(order.id),
                  'payment_intent': {'id': 'pi_test', 'latest_charge': {'created': 1789581000}}}
        calls = []
        def retrieve(session_id):
            calls.append(session_id)
            return result
        monkeypatch.setattr(gateways, 'retrieve_session', retrieve)
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: user
        with TestClient(app) as client:
            yield client, db, order, result, calls, app
    engine.dispose()


def verify(world):
    client, _, order, *_ = world
    return client.post(f'/api/v1/commerce/orders/{order.id}/payment-status')


def test_reconciles_paid_order_and_deduplicates_webhook(world):
    client, db, order, result, calls, _ = world
    response = verify(world)
    assert response.status_code == 200
    assert response.json()['data']['payment_status'] == 'paid'
    assert response.json()['data']['payment_reference'] == 'pi_test'
    assert order.paid_at is not None
    paid_at = order.paid_at
    assert verify(world).status_code == 200
    assert len(calls) == 1
    service = CommerceService(db)
    event = {'id': 'evt_test', 'type': 'checkout.session.completed', 'data': {'object': result}}
    service.webhook(event)
    assert service.webhook(event)['duplicate'] is True
    assert len(order.tracking) == 1
    assert order.paid_at == paid_at
    assert client.get(f'/api/v1/commerce/orders/{order.id}').json()['data']['status'] == 'paid'


@pytest.mark.parametrize('field,value', [('amount_total', 1), ('currency', 'usd'),
    ('client_reference_id', 'another-order'), ('id', 'cs_other'), ('livemode', True), ('payment_intent', None)])
def test_rejects_confirmation_for_wrong_order_or_amount(world, field, value):
    _, _, order, result, *_ = world
    result[field] = value
    assert verify(world).status_code == 409
    assert order.payment_status == 'pending'
    assert not order.tracking


def test_success_query_is_not_proof_of_payment(world):
    client, _, order, result, *_ = world
    result['payment_status'] = 'unpaid'
    response = client.post(f'/api/v1/commerce/orders/{order.id}/payment-status?payment=success')
    assert response.status_code == 200
    assert response.json()['data']['payment_status'] == 'pending'


def test_cannot_reconcile_another_customers_order_or_use_admin_route(world):
    client, db, order, _, calls, _ = world
    assert client.post(f'/api/v1/commerce/admin/orders/{order.id}/payment-status').status_code == 403
    order.user_id = uuid.uuid4()
    db.commit()
    assert verify(world).status_code == 404
    assert calls == []


def test_checkout_does_not_offer_payment_again_when_stripe_already_paid(world, monkeypatch):
    client, _, order, *_ = world
    def unexpected(_):
        pytest.fail('Must not create another checkout session')
    monkeypatch.setattr(gateways, 'create_session', unexpected)
    response = client.post(f'/api/v1/commerce/orders/{order.id}/checkout')
    assert response.status_code == 200
    assert response.json()['data'] == {'status': 'paid', 'url': None}


def test_expired_session_releases_stock_once(world):
    _, db, order, result, *_ = world
    variant_id = uuid.uuid4()
    stock = StockModel(variant_id=variant_id, branch_id=order.branch_id, quantity=4)
    db.add(stock)
    order.items = [{'variant_id': str(variant_id), 'quantity': 1}]
    db.commit()
    result.update(status='expired', payment_status='unpaid')
    assert verify(world).json()['data']['status'] == 'expired'
    assert verify(world).status_code == 200
    db.refresh(stock)
    assert stock.quantity == 5


def test_return_urls_identify_order_without_auth_tokens(world, monkeypatch):
    _, _, order, *_ = world
    captured = {}
    def capture(method, path, data, key):
        captured.update(data)
        return {'id': 'cs_test', 'url': 'https://checkout.stripe.com/test'}
    monkeypatch.setattr(gateways, 'stripe_request', capture)
    gateways.create_session(order)
    assert f'pedido={order.id}' in captured['success_url']
    assert f'pedido={order.id}' in captured['cancel_url']
    assert 'token' not in captured['success_url']
