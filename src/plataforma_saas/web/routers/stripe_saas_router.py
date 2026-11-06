from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session
from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db, set_rls_context
from src.infrastructure.security.authorization import require_permissions, require_platform_permissions
from src.infrastructure.security.tenancy import TenantScope
from src.plataforma_saas.web.schemas.stripe_saas import (
    BillingCheckoutIn, BillingCheckoutOut, BillingPortalOut, BillingPlanOut,
    PlanStripePriceIn, PlanStripePriceOut, StripeAccountOut, StripeOnboardingOut, StripeReceived,
)
from src.plataforma_saas.application.billing_stripe import StripeBilling
from src.shared.responses.api_response import ApiResponse

router = APIRouter(tags=["PAQ-06 · Stripe SaaS"])
BillingWriter = Annotated[UserModel, Depends(require_permissions("billing.manage"))]
BillingReader = Annotated[UserModel, Depends(require_permissions("my_subscription.read"))]
PaymentWriter = Annotated[UserModel, Depends(require_permissions("payment_methods.write"))]
PlanWriter = Annotated[UserModel, Depends(require_platform_permissions("plans.write"))]


def _pending():
    raise HTTPException(501, "Implementación pendiente de Stripe SaaS.")


async def cuerpo_crudo(request: Request) -> bytes:
    """Stripe firma los bytes exactos: se leen aquí para que el endpoint siga siendo
    `def` y su trabajo de base corra en el pool de hilos, no en el bucle de eventos."""
    return await request.body()


RawBody = Annotated[bytes, Depends(cuerpo_crudo)]


@router.get("/tenant/billing/plans", response_model=ApiResponse[list[BillingPlanOut]])
def billing_plans(ctx: TenantScope, actor: BillingReader, db: Session = Depends(get_db)):
    return ApiResponse(data=StripeBilling(db).planes_disponibles())


@router.post("/tenant/billing/checkout", response_model=ApiResponse[BillingCheckoutOut])
def billing_checkout(data: BillingCheckoutIn, ctx: TenantScope, actor: BillingWriter, db: Session = Depends(get_db)):
    result = StripeBilling(db).crear_checkout(ctx.tenant_id, data.plan_code)
    db.commit()  # conserva el cliente de Stripe creado para la empresa
    return ApiResponse(data=result)


@router.post("/tenant/billing/portal", response_model=ApiResponse[BillingPortalOut])
def billing_portal(ctx: TenantScope, actor: BillingWriter, db: Session = Depends(get_db)):
    return ApiResponse(data=StripeBilling(db).crear_portal(ctx.tenant_id))


@router.post("/stripe/billing/webhook", response_model=StripeReceived)
def billing_webhook(body: RawBody, stripe_signature: str | None = Header(default=None), db: Session = Depends(get_db)):
    set_rls_context(db, is_platform=True)  # RN-RLS: webhooks de Stripe → plataforma
    result = StripeBilling(db).procesar_webhook(body, stripe_signature)
    db.commit()
    return result


@router.get("/tenant/payments/stripe-account", response_model=ApiResponse[StripeAccountOut])
def stripe_account(ctx: TenantScope, actor: PaymentWriter):
    return _pending()


@router.post("/tenant/payments/stripe-account/onboarding", response_model=ApiResponse[StripeOnboardingOut])
def stripe_onboarding(ctx: TenantScope, actor: PaymentWriter):
    return _pending()


@router.post("/stripe/connect/webhook", response_model=StripeReceived)
async def connect_webhook(request: Request):
    return _pending()


@router.put("/platform/plans/{plan_id}/stripe-price", response_model=ApiResponse[PlanStripePriceOut])
def stripe_plan_price(plan_id: UUID, data: PlanStripePriceIn, actor: PlanWriter, db: Session = Depends(get_db)):
    result = StripeBilling(db).vincular_precio(plan_id, data.stripe_price_id_month)
    db.commit()
    return ApiResponse(data=result)
