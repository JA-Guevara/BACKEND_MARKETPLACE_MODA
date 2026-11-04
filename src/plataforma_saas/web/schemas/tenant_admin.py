from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr


class PlanUsage(BaseModel):
    active_branches: int
    max_branches: int | None = None


class OrderBrief(BaseModel):
    id: UUID
    code: str
    total: Decimal
    channel: Literal["online", "pos"]
    payment_method: str
    status: str
    created_at: datetime


class ReservationBrief(BaseModel):
    id: UUID
    customer_name: str
    items: int
    starts_at: datetime
    status: str
    origin: Literal["online", "offline"]


class TenantDashboard(BaseModel):
    sales_today: Decimal
    orders_today: int
    sales_delta_pct: float | None = None
    reservations_today: int
    in_fitting_room: int
    critical_stock: int
    plan_usage: PlanUsage
    recent_orders: list[OrderBrief]
    upcoming_reservations: list[ReservationBrief]


class TenantProfile(BaseModel):
    id: UUID
    legal_name: str
    trade_name: str
    tax_id: str
    slug: str
    contact_email: str
    phone: str | None = None


class TenantProfileUpdate(BaseModel):
    trade_name: str | None = None
    contact_email: EmailStr | None = None
    phone: str | None = None

    model_config = ConfigDict(extra="forbid")
