import json
from pathlib import Path
import pytest
from pydantic import BaseModel, ConfigDict
from src.plataforma_saas.web.schemas import stripe_saas as schema
from src.shared.responses.api_response import ApiResponse


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    details: dict | None


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    success: bool
    error: ErrorBody


def test_fixtures_cierre_coinciden_con_contrato():
    folder = Path(__file__).resolve().parents[4] / 'docs/PS-PX-cierre-y-publicacion/contrato/fixtures'
    if not folder.exists():
        pytest.skip('Fixtures documentales no distribuidos con el checkout.')
    models = {
        'billing_checkout_peticion': schema.BillingCheckoutIn,
        'billing_checkout_respuesta': ApiResponse[schema.BillingCheckoutOut],
        'billing_portal_respuesta': ApiResponse[schema.BillingPortalOut],
        'cuenta_cobro_no_conectada': ApiResponse[schema.StripeAccountOut],
        'cuenta_cobro_activa': ApiResponse[schema.StripeAccountOut],
        'cuenta_cobro_pendiente': ApiResponse[schema.StripeAccountOut],
        'onboarding_respuesta': ApiResponse[schema.StripeOnboardingOut],
        'precio_plan_peticion': schema.PlanStripePriceIn,
        'precio_plan_respuesta': ApiResponse[schema.PlanStripePriceOut],
        'integracion_ventas': ApiResponse[schema.IntegrationSalesOut],
        'integracion_stock': ApiResponse[schema.IntegrationStockOut],
        'stripe_evento_invoice_paid': schema.StripeEventIn,
        'stripe_evento_account_updated': schema.StripeEventIn,
        'stripe_webhook_ok': schema.StripeReceived,
        'connect_webhook_ok': schema.StripeReceived,
        'webhook_evento_venta': schema.IntegrationEventOut,
    }
    for path in folder.glob('*.json'):
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('success') is False:
            ErrorEnvelope.model_validate(data)
        elif path.stem in models:
            models[path.stem].model_validate(data)
        elif path.stem == 'billing_planes_disponibles':
            ApiResponse[list[schema.BillingPlanOut]].model_validate(data)
        elif path.stem == 'checkout_pedido_respuesta':
            assert data['success'] is True and data['data']['checkout_url'].startswith('https://')
        elif path.stem == 'webhook_recibido':
            assert data == {'status': 200}
        elif path.stem == 'signup_slug':
            assert isinstance(data['data']['available'], bool)
        else:
            pytest.fail('Fixture sin esquema: ' + path.stem)
