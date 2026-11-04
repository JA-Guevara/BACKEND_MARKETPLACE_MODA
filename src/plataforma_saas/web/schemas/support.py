import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.auth.infrastructure.http.schemas import SubscriptionSummary, TenantSummary


class SupportSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10, max_length=300)
    duration_minutes: Literal[15, 60, 120, 240] = 60


class SupportSessionExtend(BaseModel):
    minutes: Literal[15, 30, 60] = 30


class SupportSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str
    platform_user_id: uuid.UUID
    platform_user_name: str
    reason: str
    duration_minutes: int
    started_at: datetime
    expires_at: datetime
    ended_at: datetime | None = None
    end_reason: str | None = None
    actions_count: int = 0
    is_active: bool = False


class SupportSessionStart(BaseModel):
    session: SupportSessionResponse
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    tenant: TenantSummary
    subscription: SubscriptionSummary | None = None
    permissions: list[str]
