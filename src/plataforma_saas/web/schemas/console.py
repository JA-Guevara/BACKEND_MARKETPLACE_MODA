from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


class TenantCounters(BaseModel):
    active: int
    inactive: int
    suspended: int
    expiring_7d: int
    near_limit: int


class PlanSlice(BaseModel):
    plan_code: str
    plan_name: str
    tenants: int


class MonthCount(BaseModel):
    month: str
    count: int


class PlatformUsage(BaseModel):
    active_branches: int
    branch_capacity: int
    ai_reports_month: int
    tryon_jobs_month: int
    orders_30d: int
    reservations_30d: int


class AttentionItem(BaseModel):
    tenant_id: UUID
    trade_name: str
    kind: Literal["expiring", "at_limit", "suspended"]
    detail: str


class ActivityItem(BaseModel):
    id: UUID
    action: str
    description: str
    created_at: datetime
    tenant_name: str | None = None


class PlatformDashboard(BaseModel):
    mrr_estimate: Decimal
    currency: str = "BOB"
    tenants: TenantCounters
    plan_distribution: list[PlanSlice]
    signups_by_month: list[MonthCount]
    usage: PlatformUsage
    attention: list[AttentionItem]
    recent_activity: list[ActivityItem]


class QuotaItem(BaseModel):
    code: str
    label: str
    used: int
    limit: int | None = None


class TenantOverview(BaseModel):
    sales_30d: Decimal
    orders_30d: int
    online_orders_30d: int
    pos_orders_30d: int
    reservations_30d: int
    offline_reservations_30d: int
    active_users: int
    users_by_role: dict[str, int]
    quotas: list[QuotaItem]
    last_activity_at: datetime | None = None


class GlobalUserResponse(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    email: str
    phone: str | None = None
    tenant_id: UUID | None = None
    tenant_name: str | None = None
    roles: list[str] = Field(default_factory=list)
    is_active: bool
    is_verified: bool
    must_change_password: bool = False
    temporary_password: str | None = None
    locked_until: datetime | None = None
    last_login_at: datetime | None = None
    created_at: datetime


class BranchSummary(BaseModel):
    id: UUID
    name: str
    city_name: str
    is_active: bool
    cash_points: int
