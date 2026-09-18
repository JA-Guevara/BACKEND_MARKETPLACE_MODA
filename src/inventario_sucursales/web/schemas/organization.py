import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class CityCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    department: str = Field(min_length=2, max_length=100)
    country: str = Field(default="Bolivia", min_length=2, max_length=100)


class CityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    department: str | None = Field(default=None, min_length=2, max_length=100)
    country: str | None = Field(default=None, min_length=2, max_length=100)


class CityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    department: str
    country: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SupplierCreate(BaseModel):
    business_name: str = Field(min_length=2, max_length=180)
    trade_name: str | None = Field(default=None, max_length=180)
    tax_id: str = Field(min_length=3, max_length=50)
    contact_name: str | None = Field(default=None, max_length=150)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    notes: str | None = None

    @field_validator("tax_id")
    @classmethod
    def normalize_tax_id(cls, value: str) -> str:
        return value.strip().upper()


class SupplierUpdate(BaseModel):
    business_name: str | None = Field(default=None, min_length=2, max_length=180)
    trade_name: str | None = Field(default=None, max_length=180)
    tax_id: str | None = Field(default=None, min_length=3, max_length=50)
    contact_name: str | None = Field(default=None, max_length=150)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    notes: str | None = None


class SupplierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_name: str
    trade_name: str | None
    tax_id: str
    contact_name: str | None
    email: EmailStr | None
    phone: str | None
    address: str | None
    city: str | None
    notes: str | None
    is_active: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BranchCreate(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    name: str = Field(min_length=2, max_length=150)
    city_id: uuid.UUID
    address: str = Field(min_length=5, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    # Casilla que recibe los avisos de reserva de esta sucursal (RF11).
    notification_email: EmailStr | None = None
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    opening_hours: dict | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class BranchUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=30)
    name: str | None = Field(default=None, min_length=2, max_length=150)
    city_id: uuid.UUID | None = None
    address: str | None = Field(default=None, min_length=5, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    # Casilla que recibe los avisos de reserva de esta sucursal (RF11).
    notification_email: EmailStr | None = None
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    opening_hours: dict | None = None


class BranchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    city_id: uuid.UUID
    city: CityResponse
    address: str
    phone: str | None
    notification_email: str | None = None
    latitude: Decimal | None
    longitude: Decimal | None
    opening_hours: dict | None
    is_active: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CashPointCreate(BaseModel):
    branch_id: uuid.UUID
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=2, max_length=100)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class CashPointUpdate(BaseModel):
    branch_id: uuid.UUID | None = None
    code: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=2, max_length=100)


class CashPointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    branch_id: uuid.UUID
    code: str
    name: str
    is_active: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
