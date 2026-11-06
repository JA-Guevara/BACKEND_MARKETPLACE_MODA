"""Contrato de Stripe SaaS e integraciones, sin identificadores privados de cuentas."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BillingCheckoutIn(StrictModel):
    plan_code: str = Field(min_length=1, max_length=30)
    interval: Literal["month"]


class BillingCheckoutOut(StrictModel):
    checkout_url: str
    expires_at: AwareDatetime


class BillingPortalOut(StrictModel):
    portal_url: str


class StripeAccountOut(StrictModel):
    status: Literal["not_connected", "pending", "active", "restricted"]
    charges_enabled: bool
    payouts_enabled: bool
    details_submitted: bool
    account_ref: str | None
    updated_at: datetime | None


class StripeOnboardingOut(StrictModel):
    onboarding_url: str
    expires_at: AwareDatetime


class PlanStripePriceIn(StrictModel):
    stripe_price_id_month: str | None = Field(default=None, pattern=r"^price_[A-Za-z0-9_]+$", max_length=100)


class PlanStripePriceOut(StrictModel):
    plan_id: UUID
    code: str
    stripe_price_id_month: str | None
    stripe_ready: bool


class BillingPlanOut(StrictModel):
    code: str
    name: str
    reference_price: str
    stripe_ready: bool


class StripeReceived(StrictModel):
    received: Literal[True]


class IntegrationSale(StrictModel):
    id: UUID
    number: str
    channel: str
    branch_code: str
    total: str
    currency: str
    confirmed_at: AwareDatetime


class IntegrationSalesOut(StrictModel):
    items: list[IntegrationSale]
    next_since: AwareDatetime | None


class IntegrationStockItem(StrictModel):
    sku: str
    branch_code: str
    quantity: int


class IntegrationStockOut(StrictModel):
    items: list[IntegrationStockItem]


class StripeEventIn(BaseModel):
    # Stripe adds fields without versioning our local envelope.
    id: str = Field(min_length=1, max_length=255)
    type: str
    account: str | None = None
    livemode: bool = False
    data: dict


class IntegrationEventOut(StrictModel):
    id: UUID
    type: str
    created_at: AwareDatetime
    tenant: dict[str, str]
    data: dict
