import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.auth.infrastructure.http.schemas import SubscriptionSummary, TenantSummary


class SupportSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10, max_length=300)
    duration_minutes: Literal[15, 30, 60, 120, 240] = 60
    mode: str = "WRITE"
    landing_module: str | None = None


class SupportSessionCreateWithTenant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: uuid.UUID
    reason: str = Field(min_length=10, max_length=300)
    duration_minutes: Literal[15, 30, 60, 120, 240] = 60
    mode: str = "WRITE"
    landing_module: str | None = None


class SupportSessionExtend(BaseModel):
    minutes: Literal[15, 30, 60] = 30


class SupportSessionUpgrade(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=10, max_length=300)


class SupportSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str
    platform_user_id: uuid.UUID
    platform_user_name: str
    reason: str
    duration_minutes: int
    mode: str = "WRITE"
    landing_module: str | None = None
    started_at: datetime
    expires_at: datetime
    ended_at: datetime | None = None
    end_reason: str | None = None
    actions_count: int = 0
    is_active: bool = False
    status: str = "active"
    approved_by_user_id: uuid.UUID | None = None
    approved_at: datetime | None = None
    decision_reason: str | None = None
    request_expires_at: datetime | None = None
    is_emergency: bool = False


class SupportSessionStart(BaseModel):
    session: SupportSessionResponse
    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int = 0
    tenant: TenantSummary | None = None
    subscription: SubscriptionSummary | None = None
    permissions: list[str] = Field(default_factory=list)


SupportSessionStartResponse = SupportSessionStart


class SupportApprovalRequest(BaseModel):
    minutes: Literal[15, 30, 60] = 30


class SupportRejectionRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=255)


class SupportPolicyUpdate(BaseModel):
    mode: Literal["require_approval", "allow_read_only"]


class SupportEmergencyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: uuid.UUID
    reason: str = Field(min_length=20, max_length=300)
    duration_minutes: Literal[15, 30] = 30
    landing_module: str | None = None
