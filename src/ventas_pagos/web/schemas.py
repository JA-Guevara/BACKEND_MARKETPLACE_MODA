from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class Quantity(BaseModel):
    quantity: int = Field(ge=1, le=99)


class StockQuantity(BaseModel):
    branch_id: UUID
    quantity: int = Field(ge=0, le=1000000)


class Address(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    recipient: str = Field(min_length=2, max_length=200)
    phone: str = Field(min_length=6, max_length=30)
    line1: str = Field(min_length=5, max_length=300)
    city: str = Field(min_length=2, max_length=100)
    country: str = Field(default="BO", min_length=2, max_length=2)
    postal_code: str | None = Field(default=None, max_length=20)


class CheckoutOrder(BaseModel):
    branch_id: UUID
    address: Address
    payment_method: Literal["stripe", "manual"]


class TrackingUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    status: Literal["processing", "shipped", "delivered"]
    carrier: str | None = Field(default=None, max_length=120)
    tracking_number: str | None = Field(default=None, max_length=150)
    note: str = Field(default="", max_length=1000)


class ManualPayment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    method: Literal["cash", "transfer"]
    reference: str = Field(min_length=3, max_length=255)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    first_name: str = Field(min_length=2, max_length=100)
    last_name: str = Field(min_length=2, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
