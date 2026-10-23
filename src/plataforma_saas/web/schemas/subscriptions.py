from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from src.auth.infrastructure.http.schemas import TenantSummary


class SubscriptionView(BaseModel):
    id: UUID
    plan_code: str
    plan_name: str
    start_date: date
    end_date: date
    status: str
    days_left: int
    reason: str | None
    reference_price: Decimal | None = None


class SubscriptionUsage(BaseModel):
    active_branches: int
    max_active_branches: int


class SubscriptionDetail(BaseModel):
    tenant: TenantSummary
    current: SubscriptionView
    usage: SubscriptionUsage
    features: dict[str, bool]
    limits: dict[str, int]
    history: list[SubscriptionView]


class ChangePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    plan_code: str
    start_date: date | None = None
    reason: str = Field(min_length=3, max_length=300)


class RenewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str | None = Field(default=None, max_length=300)


class StatusChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: Literal["ACTIVA", "SUSPENDIDA", "CANCELADA"]
    reason: str = Field(min_length=3, max_length=300)
