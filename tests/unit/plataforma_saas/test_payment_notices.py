"""Notificaciones con pagos simulados: firma, destinatario, tenant y sucursal reales."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from src.infrastructure.config.settings import settings
from src.infrastructure.security.access_context import AccessContext
from src.inventario_sucursales.infrastructure.models.organization import UserBranchModel
from src.notificaciones.application.use_cases.consultar_avisos import ConsultarAvisos
from src.ventas_pagos.infrastructure import gateways
from src.ventas_pagos.infrastructure.models import OrderReturnModel
from tests.unit.plataforma_saas.test_stripe_connect import activate, pending_order
from tests.unit.plataforma_saas.test_stripe_billing import post_event, setup_customer


def feed(w, user):
    response = w.client.get('/api/v1/notifications', headers=w.headers(user))
    assert response.status_code == 200, response.text
    return response.json()['data']


def test_checkout_pendiente_cuenta_erronea_y_webhook_confirmado_sin_duplicar(world, monkeypatch):
    activate(world, 0)
    activate(world, 1)
    order = pending_order(world)
    calls = []
    def stripe(method, path, data=None, key=None, **kwargs):
        calls.append(kwargs)
        return {'id': 'cs_test_notice', 'url': 'https://checkout.stripe.com/c/pay/simulated'}
    monkeypatch.setattr(gateways, 'stripe_request', stripe)
    monkeypatch.setattr(settings, 'stripe_connect_webhook_secret', 'whsec_unit_only')
    result = world.client.post(f'/api/v1/commerce/orders/{order.id}/checkout', headers=world.headers(world.customers[0]))
    assert result.status_code == 200, result.text
    assert calls[0]['stripe_account'] == 'acct_test_0'
    assert not any(n['estado'] == 'paid' for n in feed(world, world.customers[0]))
    event = {'id': 'evt_notice', 'type': 'checkout.session.completed', 'account': 'acct_test_1', 'data': {'object': {
        'id': 'cs_test_notice', 'mode': 'payment', 'payment_status': 'paid', 'currency': 'bob', 'amount_total': 15000,
        'client_reference_id': str(order.id), 'payment_intent': 'pi_test_notice'}}}
    assert post_event(world, event, 'connect').status_code == 200
    assert not any(n['estado'] == 'paid' for n in feed(world, world.customers[0]))
    event.update(id='evt_notice_correct', account='acct_test_0')
    for _ in range(2):
        assert post_event(world, event, 'connect').status_code == 200
    notices = feed(world, world.customers[0])
    payments = [n for n in notices if n['estado'] == 'paid']
    assert len(payments) == 1
    assert payments[0]['event_key'] == f'payment:{order.id}:paid'
    assert payments[0]['importante'] and payments[0]['tono'] == 'success'
    assert '150.00 BOB' in payments[0]['detalle']
    assert feed(world, world.customers[1]) == []
    assert any(n['event_key'] == payments[0]['event_key'] for n in feed(world, world.admins[0]))
    assert feed(world, world.admins[1]) == []


def test_historial_filtra_tenant_aun_si_el_mismo_usuario_figura_en_dos_empresas(world):
    first, second = pending_order(world, 0), pending_order(world, 1)
    for order in (first, second):
        order.user_id = world.customers[0].id
        order.payment_status = 'paid'
        order.paid_at = datetime.now(timezone.utc)
    world.db.commit()
    assert [n['referencia'] for n in feed(world, world.customers[0])] == [first.number]


def test_personal_sin_sucursal_no_recibe_pagos_ajenos(world):
    order = pending_order(world)
    order.paid_at = datetime.now(timezone.utc)
    order.payment_status = 'paid'
    world.db.commit()
    user = world.admins[0]
    user.roles = [world.cashier_role]
    world.db.commit()
    context = AccessContext(user, user.tenant_id, None, frozenset({'commerce.read'}))
    assert ConsultarAvisos(world.db).execute(user, context=context) == []
    world.db.add(UserBranchModel(tenant_id=user.tenant_id, user_id=user.id, branch_id=world.branches[0].id))
    world.db.commit()
    notices = ConsultarAvisos(world.db).execute(user, context=context)
    assert len(notices) == 1 and notices[0]['enlace'].startswith('/admin/pedidos')


def test_pago_plan_notifica_solo_a_administrador_y_plataforma_no_a_cliente(world, monkeypatch):
    monkeypatch.setattr(settings, 'stripe_billing_webhook_secret', 'whsec_unit_only')
    setup_customer(world)
    event = {'id': 'evt_plan_notice', 'type': 'invoice.paid', 'data': {'object': {
        'id': 'in_plan_notice', 'customer': 'cus_test_a', 'subscription': 'sub_test_a', 'currency': 'bob',
        'amount_paid': 35000, 'period_start': int(datetime.now().timestamp()), 'period_end': int((datetime.now()+timedelta(days=30)).timestamp())}}}
    assert post_event(world, event).status_code == 200
    notices = feed(world, world.admins[0])
    assert len(notices) == 1 and notices[0]['titulo'] == 'Pago del plan confirmado'
    assert '350.00 BOB' in notices[0]['detalle']
    assert feed(world, world.customers[0]) == feed(world, world.admins[1]) == []
    platform = feed(world, world.platform)
    assert len(platform) == 1 and platform[0]['enlace'].endswith(str(world.tenants[0].id))


def test_cambio_reembolso_solo_se_anuncia_cuando_esta_confirmado(world):
    order = pending_order(world)
    change = OrderReturnModel(id=uuid4(), tenant_id=order.tenant_id, order_id=order.id, branch_id=order.branch_id,
        user_id=order.user_id, reason='[CAMBIO] Otra talla', status='approved', refund_amount=Decimal('20'),
        difference_amount=Decimal('-20'), currency='BOB', settlement_status='pending_refund', items=[],
        resolved_at=datetime.now(timezone.utc))
    world.db.add(change); world.db.commit()
    assert not any(n['estado'] == 'refunded' for n in feed(world, world.customers[0]))
    change.settlement_status = 'refunded'; world.db.commit()
    paid = [n for n in feed(world, world.customers[0]) if n['estado'] == 'refunded']
    assert len(paid) == 1 and '20.00 BOB' in paid[0]['detalle']
