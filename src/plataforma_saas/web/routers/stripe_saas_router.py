from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.security.authorization import require_permissions, require_platform_permissions
from src.infrastructure.security.tenancy import TenantScope
from src.plataforma_saas.web.schemas.stripe_saas import (
    BillingCheckoutIn, BillingCheckoutOut, BillingPortalOut, BillingPlanOut,
    PlanStripePriceIn, PlanStripePriceOut, StripeAccountOut, StripeOnboardingOut, StripeReceived,
)
from src.shared.responses.api_response import ApiResponse

router = APIRouter(tags=["PAQ-06 · Stripe SaaS"])
BillingWriter = Annotated[UserModel, Depends(require_permissions("billing.manage"))]
BillingReader = Annotated[UserModel, Depends(require_permissions("my_subscription.read"))]
PaymentWriter = Annotated[UserModel, Depends(require_permissions("payment_methods.write"))]
PlanWriter = Annotated[UserModel, Depends(require_platform_permissions("plans.write"))]


def _pending():
    raise HTTPException(501, "Implementación pendiente de Stripe SaaS.")


@router.get("/tenant/billing/plans", response_model=ApiResponse[list[BillingPlanOut]])
def billing_plans(ctx: TenantScope, actor: BillingReader):
    return _pending()


@router.post("/tenant/billing/checkout", response_model=ApiResponse[BillingCheckoutOut])
def billing_checkout(data: BillingCheckoutIn, ctx: TenantScope, actor: BillingWriter):
    return _pending()


@router.post("/tenant/billing/portal", response_model=ApiResponse[BillingPortalOut])
def billing_portal(ctx: TenantScope, actor: BillingWriter):
    return _pending()


@router.post("/stripe/billing/webhook", response_model=StripeReceived)
async def billing_webhook(request: Request):
    return _pending()


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
def stripe_plan_price(plan_id: UUID, data: PlanStripePriceIn, actor: PlanWriter):
    return _pending()
