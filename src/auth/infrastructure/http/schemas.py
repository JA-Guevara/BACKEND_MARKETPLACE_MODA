import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    first_name: str = Field(min_length=2, max_length=100)
    last_name: str = Field(min_length=2, max_length=100)
    phone: str | None = Field(default=None, max_length=30)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_slug: str | None = Field(default=None, max_length=60, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    platform_login: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=12, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class PermissionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str


class RoleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    permissions: list[PermissionSummary] = Field(default_factory=list)


class TenantSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    slug: str
    trade_name: str
    status: str


class ModuleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    origin: str
    expires_at: datetime | None = None


class SubscriptionSummary(BaseModel):
    plan_code: str
    plan_name: str
    status: str
    start_date: date
    end_date: date
    days_left: int
    features: dict[str, bool]
    modules: list[ModuleSummary] = Field(default_factory=list)
    limits: dict[str, int]
    lifecycle_state: str | None = None
    grace_until: datetime | None = None
    read_only_since: datetime | None = None
    next_notice: str | None = None


class AuthorizedBranchSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    is_default: bool = False


class AuthUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    first_name: str
    last_name: str
    phone: str | None
    is_active: bool
    is_verified: bool
    read_only: bool = False
    must_change_password: bool = False
    tenant: TenantSummary | None = None
    subscription: SubscriptionSummary | None = None
    support: Any | None = None
    authorized_branches: list[AuthorizedBranchSummary] = Field(default_factory=list)
    last_login_at: datetime | None
    roles: list[RoleSummary] = Field(default_factory=list)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthUserResponse

class UserSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_label: str | None = None
    ip_prefix: str | None = None
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime


class RevokeOthersRequest(BaseModel):
    current_jti: str | None = None
    current_refresh_token: str | None = None
    current_session_id: uuid.UUID | None = None
    refresh_token: str | None = None
    session_id: uuid.UUID | None = None

