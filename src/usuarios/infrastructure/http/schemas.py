import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.auth.infrastructure.http.schemas import RoleSummary


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    first_name: str = Field(min_length=2, max_length=100)
    last_name: str = Field(min_length=2, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    document_number: str | None = Field(default=None, max_length=50)
    role_ids: list[uuid.UUID] = Field(min_length=1)
    is_verified: bool = False

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    first_name: str | None = Field(default=None, min_length=2, max_length=100)
    last_name: str | None = Field(default=None, min_length=2, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    document_number: str | None = Field(default=None, max_length=50)
    is_verified: bool | None = None

    @field_validator("email")
    @classmethod
    def normalize_optional_email(cls, value: EmailStr | None) -> str | None:
        return str(value).strip().lower() if value else None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    first_name: str
    last_name: str
    phone: str | None
    document_number: str | None
    is_active: bool
    is_verified: bool
    failed_login_attempts: int
    locked_until: datetime | None
    last_login_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    roles: list[RoleSummary] = Field(default_factory=list)


class AssignRolesRequest(BaseModel):
    role_ids: list[uuid.UUID] = Field(min_length=1)


class AddressCreate(BaseModel):
    label: str = Field(default="Principal", max_length=50)
    recipient_name: str = Field(min_length=2, max_length=200)
    phone: str = Field(min_length=5, max_length=30)
    city: str = Field(min_length=2, max_length=100)
    address_line: str = Field(min_length=5, max_length=255)
    reference: str | None = Field(default=None, max_length=255)
    is_default: bool = False


class AddressUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=50)
    recipient_name: str | None = Field(default=None, min_length=2, max_length=200)
    phone: str | None = Field(default=None, min_length=5, max_length=30)
    city: str | None = Field(default=None, min_length=2, max_length=100)
    address_line: str | None = Field(default=None, min_length=5, max_length=255)
    reference: str | None = Field(default=None, max_length=255)
    is_default: bool | None = None


class AddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    label: str
    recipient_name: str
    phone: str
    city: str
    address_line: str
    reference: str | None
    is_default: bool
    created_at: datetime
    updated_at: datetime
