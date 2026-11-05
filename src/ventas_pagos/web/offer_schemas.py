"""Esquemas Pydantic para ofertas y promociones (CU-11)."""
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
import uuid

from pydantic import BaseModel, Field, model_validator


class OfferTargetIn(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}

    type: Literal["PRODUCT", "VARIANT", "CATEGORY", "SEASON", "COLLECTION", "ALL"] = "ALL"
    ids: list[uuid.UUID] = Field(default_factory=list)


class OfferTargetOut(BaseModel):
    type: str
    ids: list[uuid.UUID]


class OfferIn(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}

    name: str = Field(min_length=3, max_length=160)
    code: str | None = Field(default=None, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=500)
    discount_type: Literal["percent", "fixed", "clearance", "free_shipping"]
    discount_value: Decimal = Field(default=Decimal(0), ge=0, le=1000000)
    minimum_order: Decimal = Field(default=Decimal(0), ge=0, le=1000000)
    target: OfferTargetIn = Field(default_factory=OfferTargetIn)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_uses: int | None = Field(default=None, ge=1, le=1000000)
    per_user_limit: int | None = Field(default=None, ge=1, le=1000)
    applies_online: bool = True
    applies_pos: bool = True
    applies_offline: bool = False
    is_active: bool = True

    @model_validator(mode="after")
    def validate_offer(self):
        # applies_offline solo permitido sin código (cupones no van offline)
        if self.code and self.applies_offline:
            raise ValueError("Las ofertas sin conexión no pueden exigir código de cupón.")
        if self.discount_type == "percent" and not (0 < self.discount_value <= 90):
            raise ValueError("El porcentaje de descuento debe estar entre 0,01 y 90%.")
        if self.discount_type == "fixed" and self.discount_value <= 0:
            raise ValueError("El descuento de monto fijo debe ser mayor a cero.")
        if self.discount_type == "clearance" and self.discount_value <= 0:
            raise ValueError("El precio de liquidación debe ser mayor a cero.")
        if self.discount_type == "free_shipping" and self.discount_value != 0:
            raise ValueError("Envío gratis no lleva importe de descuento.")
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValueError("La fecha de fin debe ser posterior a la de inicio.")
        return self


class OfferUpdate(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}

    name: str | None = Field(default=None, min_length=3, max_length=160)
    description: str | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, le=1000000)
    target: OfferTargetIn | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_uses: int | None = Field(default=None, ge=1)
    per_user_limit: int | None = Field(default=None, ge=1)
    applies_online: bool | None = None
    applies_pos: bool | None = None
    applies_offline: bool | None = None
    is_active: bool | None = None


class OfferOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str | None
    description: str | None
    discount_type: str
    discount_value: Decimal
    minimum_order: Decimal
    target: OfferTargetOut
    starts_at: datetime | None
    ends_at: datetime | None
    max_uses: int | None
    uses_count: int
    per_user_limit: int | None
    is_active: bool
    applies_online: bool
    applies_pos: bool
    applies_offline: bool
    status: Literal["ACTIVA", "PROGRAMADA", "VENCIDA", "INACTIVA", "AGOTADA"]
    created_at: datetime
    deactivated_at: datetime | None


class OfferPreviewItem(BaseModel):
    product_name: str
    variant: str
    regular: Decimal
    final: Decimal


class OfferPreview(BaseModel):
    items: list[OfferPreviewItem]
    errors: list[str]


class PrecioPublico(BaseModel):
    base_price: Decimal
    offer_price: Decimal | None = None
    offer_name: str | None = None
    offer_ends_at: datetime | None = None
