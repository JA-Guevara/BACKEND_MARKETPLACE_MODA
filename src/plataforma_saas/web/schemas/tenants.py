from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class TenantAdminInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    first_name: str = Field(min_length=2, max_length=80)
    last_name: str = Field(min_length=2, max_length=80)
    email: EmailStr


class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    legal_name: str = Field(min_length=3, max_length=200)
    trade_name: str = Field(min_length=2, max_length=150)
    tax_id: str = Field(pattern=r"^[0-9]{5,20}$")
    slug: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{1,58})[a-z0-9]$")
    contact_email: EmailStr
    phone: str | None = Field(default=None, max_length=30)
    admin: TenantAdminInput
    plan_code: str
    start_date: date | None = None


class TenantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    legal_name: str | None = Field(default=None, min_length=3, max_length=200)
    trade_name: str | None = Field(default=None, min_length=2, max_length=150)
    contact_email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)


class TenantStatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=3, max_length=300)


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    legal_name: str
    trade_name: str
    tax_id: str
    slug: str
    contact_email: str
    phone: str | None
    status: str
    created_at: datetime
    plan_code: str | None = None
    plan_name: str | None = None
    subscription_status: str | None = None
    end_date: date | None = None
    active_branches: int = 0
    admin_email: str | None = None
    admin_password_set: bool = False


class TenantStats(BaseModel):
    active: int
    professional: int
    expiring_7d: int
    suspended: int


class ActivityItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    action: str
    description: str
    actor_email: str | None
    created_at: datetime
