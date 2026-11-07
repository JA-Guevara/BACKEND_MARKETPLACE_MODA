"""Optativo: alta real en Stripe TEST con empresas y SQLite locales.

python tests/e2e/stripe_connect_v2_smoke.py --expected-account acct_... --env-file .env
No usa Supabase, no acepta condiciones ni simula cuentas habilitadas.
Los IDs TEST de las dos cuentas creadas se muestran para su revisión en Stripe.
"""
import argparse
import json
from pathlib import Path
import runpy
import sys

import httpx
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-account', required=True)
    parser.add_argument('--env-file', default='.env')
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[2]
    key = dotenv_values(args.env_file).get('STRIPE_SECRET_KEY') or ''
    if not key.startswith('sk_test_'):
        raise SystemExit('Se requiere STRIPE_SECRET_KEY de prueba; no se admiten claves live.')
    with httpx.Client(base_url='https://api.stripe.com/v1/', auth=(key, ''), timeout=25) as stripe:
        account = stripe.get('account')
        balance = stripe.get('balance')
        if account.status_code != 200 or balance.status_code != 200:
            raise SystemExit('No se pudo comprobar la cuenta Stripe de prueba. No se crearon recursos.')
        if account.json().get('id') != args.expected_account or balance.json().get('livemode') is not False:
            raise SystemExit('La cuenta o el modo no coincide con lo esperado. No se crearon recursos.')

    # El fixture fija APP_ENV=test, deshabilita SMTP/IA y crea SQLite temporal.
    fixture = runpy.run_path(str(backend / 'tests/e2e/offline_server.py'))
    world = fixture['world']
    from src.infrastructure.config.settings import settings
    from src.plataforma_saas.infrastructure.models.stripe_saas import TenantPaymentAccountModel
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    settings.stripe_secret_key = key
    settings.stripe_connect_enabled = True
    settings.stripe_connect_test_country = 'US'
    settings.frontend_url = 'https://frontendmarketplacemoda-production.up.railway.app'
    for index, tenant in enumerate(world.tenants):
        tenant.trade_name = 'FashionStore QA local · Empresa ' + 'AB'[index]
    world.db.commit()
    result = {'mode': 'test', 'database': 'temporary_sqlite', 'onboarding': [], 'external_sales': 'pending_holder_onboarding'}
    try:
        for index in range(2):
            headers = world.headers(world.admins[index])
            for attempt in range(2):
                response = world.client.post('/api/v1/tenant/payments/stripe-account/onboarding', headers=headers)
                if response.status_code != 200:
                    raise AssertionError(f'Alta de empresa {index}: HTTP {response.status_code}')
                link = response.json()['data']['onboarding_url']
                assert link.startswith('https://connect.stripe.com/')
            response = world.client.get('/api/v1/tenant/payments/stripe-account', headers=headers)
            assert response.status_code == 200
            state = response.json()['data']
            with Session(fixture['engine']) as db:
                accounts = db.scalars(select(TenantPaymentAccountModel).where(
                    TenantPaymentAccountModel.tenant_id == world.tenants[index].id)).all()
                assert len(accounts) == 1
                result['onboarding'].append({'company': 'AB'[index], 'account': accounts[0].stripe_account_id,
                    'state': state['status'], 'charges_enabled': state['charges_enabled'], 'reused_on_retry': True})
        assert result['onboarding'][0]['account'] != result['onboarding'][1]['account']
        # El cliente no tiene permiso para ver ni conectar cuentas de cobro.
        response = world.client.post('/api/v1/tenant/payments/stripe-account/onboarding', headers=world.headers(world.customers[0]))
        assert response.status_code == 403
        result['customer_cannot_connect'] = True
        print('ACCOUNTS_V2_EXTERNAL_SMOKE_OK', json.dumps(result))
    finally:
        world.client.close()
        world.db.close()
        fixture['engine'].dispose()
        fixture['database_file'].unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Evita que excepciones de transporte o de librerías impriman secretos.
        print('No se completó el ensayo externo:', type(error).__name__)
        sys.exit(1)
