"""QA local de compra y avisos. Stripe simulado; nunca carga credenciales reales."""
from pathlib import Path
import runpy
import time
import uvicorn

backend = Path(__file__).resolve().parents[2]
fixture = runpy.run_path(str(backend / 'tests/e2e/offline_server.py'))
world = fixture['world']
from src.infrastructure.config.settings import settings
from src.ventas_pagos.infrastructure import gateways
from tests.unit.plataforma_saas.test_stripe_connect import activate
from tests.unit.plataforma_saas.test_stripe_billing import post_event

settings.stripe_secret_key = 'sk_test_local_qa_only'
settings.stripe_connect_enabled = True
settings.stripe_connect_webhook_secret = 'whsec_unit_only'
activate(world, 0)
activate(world, 1)
sessions = {}


def stripe_request(method, path, data=None, key=None, **kwargs):
    if method == 'POST' and path == 'checkout/sessions':
        sid = 'cs_test_qa_' + str(len(sessions) + 1)
        sessions[sid] = {'id': sid, 'livemode': False, 'mode': 'payment', 'status': 'open',
            'payment_status': 'unpaid', 'amount_total': int(data['line_items[0][price_data][unit_amount]']),
            'currency': data['line_items[0][price_data][currency]'].lower(),
            'client_reference_id': data['client_reference_id'], 'payment_intent': 'pi_test_qa_' + sid,
            'account': kwargs['stripe_account']}
        return {'id': sid, 'url': 'https://checkout.stripe.com/c/pay/' + sid}
    if method == 'GET' and path.startswith('checkout/sessions/'):
        session = sessions[path.split('/')[2].split('?')[0]]
        assert kwargs['stripe_account'] == session['account']
        return session
    raise AssertionError('Stripe QA no admite ' + method + ' ' + path)


gateways.stripe_request = stripe_request


@world.app.post('/qa/pay/{sid}')
def confirm(sid: str):
    session = sessions[sid]
    session.update(status='complete', payment_status='paid')
    event = {'id': 'evt_qa_' + sid, 'type': 'checkout.session.completed', 'account': session['account'],
        'created': int(time.time()), 'data': {'object': session}}
    # Endpoint real, firma de prueba y deduplicación real del webhook.
    response = post_event(world, event, 'connect')
    assert response.status_code == 200, response.text
    return {'order': session['client_reference_id'], 'account': session['account']}


try:
    uvicorn.run(world.app, host='127.0.0.1', port=57521, log_level='error')
finally:
    world.client.close(); world.db.close(); fixture['engine'].dispose()
    fixture['database_file'].unlink(missing_ok=True)
