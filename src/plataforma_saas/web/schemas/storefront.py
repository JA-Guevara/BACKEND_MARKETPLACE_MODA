"""Esquemas Pydantic para tienda pública, marca, cobros y solicitudes (RS-3)."""
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StorefrontAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    legal_name: str
    trade_name: str
    is_published: bool
    published_at: datetime | None = None
    logo_url: str | None = None
    banner_url: str | None = None
    brand_color: str | None = None
    brand_color_dark: str | None = None
    ink_on_brand: str | None = None
    slogan: str | None = None
    about: str | None = None
    whatsapp: str | None = None
    social_links: dict[str, Any] | None = None
    shipping_policy: str | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    city: str | None = None
    is_featured: bool = False
    missing_requirements: list[str] = []


class StorefrontUpdate(BaseModel):
    brand_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    slogan: str | None = Field(default=None, max_length=160)
    about: str | None = Field(default=None, max_length=1000)
    whatsapp: str | None = Field(default=None, max_length=30)
    social_links: dict[str, Any] | None = None
    shipping_policy: str | None = Field(default=None, max_length=1000)
    seo_title: str | None = Field(default=None, max_length=70)
    seo_description: str | None = Field(default=None, max_length=160)
    city: str | None = Field(default=None, max_length=80)


class PublicStoreCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    trade_name: str
    logo_url: str | None = None
    banner_url: str | None = None
    brand_color: str | None = None
    slogan: str | None = None
    city: str | None = None
    is_featured: bool = False


class PublicStoreBranch(BaseModel):
    id: UUID
    name: str
    code: str
    address: str | None = None
    city: str | None = None
    phone: str | None = None
    opening_hours: str | None = None


class PublicStoreOut(BaseModel):
    slug: str
    trade_name: str
    logo_url: str | None = None
    banner_url: str | None = None
    brand_color: str | None = None
    brand_color_dark: str | None = None
    ink_on_brand: str | None = None
    slogan: str | None = None
    about: str | None = None
    whatsapp: str | None = None
    social_links: dict[str, Any] | None = None
    shipping_policy: str | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    city: str | None = None
    branches: list[PublicStoreBranch] = []
    payment_methods_public: list[dict[str, Any]] = []
    preview: bool = False


class PaymentMethodIn(BaseModel):
    kind: Literal["QR", "TRANSFER", "PAY_IN_STORE", "GATEWAY"]
    label: str = Field(min_length=1, max_length=80)
    qr_image_url: str | None = Field(default=None, max_length=300)
    bank_name: str | None = Field(default=None, max_length=80)
    account_holder: str | None = Field(default=None, max_length=120)
    account_number: str | None = Field(default=None, max_length=40)
    instructions: str | None = Field(default=None, max_length=500)
    is_active: bool = True
    sort_order: int = 0


class PaymentMethodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    label: str
    qr_image_url: str | None = None
    bank_name: str | None = None
    account_holder: str | None = None
    account_number: str | None = None
    instructions: str | None = None
    is_active: bool = True
    sort_order: int = 0


class PaymentInstructions(BaseModel):
    order_id: UUID
    order_number: str
    total: Decimal
    methods: list[PaymentMethodOut]


class CatalogTemplateIn(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    payload: dict[str, Any] = Field(min_length=1)


class CatalogTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None = None
    payload: dict[str, Any]
    is_active: bool
    usage_count: int = 0


class ImportResult(BaseModel):
    template_code: str
    imported_counts: dict[str, int]
    message: str


class UpgradeRequestIn(BaseModel):
    kind: Literal["PLAN", "LIMIT", "MODULE"]
    target: str = Field(min_length=1, max_length=60)
    message: str | None = Field(default=None, max_length=500)


class UpgradeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    requested_by: UUID
    kind: str
    target: str
    message: str | None = None
    status: str
    handled_by: UUID | None = None
    handled_at: datetime | None = None
    response: str | None = None
    created_at: datetime


class HandleUpgradeRequestIn(BaseModel):
    response: str = Field(min_length=1, max_length=500)


class PlatformStorefrontUpdate(BaseModel):
    is_featured: bool | None = None
    unpublish_reason: str | None = Field(default=None, max_length=500)


class UsageItem(BaseModel):
    limit_code: str
    name: str
    used: int
    limit: int | None
    percentage: float
    has_warning: bool


class OnboardingOut(BaseModel):
    completed_steps: list[str]
    pending_steps: list[str]
    is_ready_to_publish: bool
    progress_percentage: int
