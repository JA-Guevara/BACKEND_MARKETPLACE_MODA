from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class ExchangePolicyIn(BaseModel):
    exchange_days: int = Field(..., ge=1, le=180, description="Días permitidos para realizar cambios")


class ExchangePolicyOut(BaseModel):
    tenant_id: str
    exchange_days: int


class ExchangeOrderLookupItem(BaseModel):
    variant_id: str
    product_id: Optional[str] = None
    product_name: str
    sku: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    original_quantity: int
    already_exchanged_quantity: int
    available_for_exchange: int
    unit_price: Decimal
    subtotal: Decimal


class ExchangeOrderLookupOut(BaseModel):
    order_id: str
    order_number: str
    purchase_date: str
    deadline_days: int
    remaining_days: int
    can_exchange: bool
    customer_email: str
    branch_id: str
    items: List[ExchangeOrderLookupItem]


class ExchangeLineCalculateIn(BaseModel):
    original_variant_id: UUID
    returned_quantity: int = Field(..., gt=0, le=99)
    original_unit_price: Decimal = Field(..., ge=0)
    new_variant_id: UUID
    delivered_quantity: int = Field(..., gt=0, le=99)
    new_unit_price: Decimal = Field(..., ge=0)


class ExchangeCalculateIn(BaseModel):
    original_order_id: UUID | None = None
    branch_id: UUID
    lines: List[ExchangeLineCalculateIn] = Field(min_length=1, max_length=20)


class ExchangeLineCalculateOut(BaseModel):
    original_variant_id: str
    returned_quantity: int
    returned_value: Decimal
    new_variant_id: str
    delivered_quantity: int
    delivered_value: Decimal
    difference: Decimal


class ExchangeCalculateOut(BaseModel):
    total_returned_value: Decimal
    total_delivered_value: Decimal
    difference_amount: Decimal
    tipo_diferencia: Literal["PAGO_CLIENTE", "REINTEGRO_O_SALDO", "CAMBIO_DIRECTO"]
    lineas: List[ExchangeLineCalculateOut]


class ExecuteExchangeIn(BaseModel):
    original_order_id: UUID
    branch_id: UUID
    payment_method: str = "none"
    cash_received: Optional[Decimal] = Field(default=None,ge=0,max_digits=12,decimal_places=2)
    cash_returned: Optional[Decimal] = Field(default=None,ge=0,max_digits=12,decimal_places=2)
    notes: Optional[str] = None
    client_request_id: UUID
    lines: List[ExchangeLineCalculateIn] = Field(min_length=1, max_length=20)


class ExchangeSummaryItem(BaseModel):
    id: str
    original_order_id: str
    original_order_number: Optional[str] = None
    branch_id: str
    difference_amount: Decimal
    payment_method: str
    status: str
    lines_count: int
    created_at: str


class ExchangeListOut(BaseModel):
    items: List[ExchangeSummaryItem]
    total: int
    page: int
    page_size: int


class ExchangeLineDetailOut(BaseModel):
    id: str
    original_variant_id: str
    original_sku: Optional[str] = None
    original_product_name: Optional[str] = None
    returned_quantity: int
    original_unit_price: Decimal
    returned_total: Decimal
    new_variant_id: str
    new_sku: Optional[str] = None
    new_product_name: Optional[str] = None
    delivered_quantity: int
    new_unit_price: Decimal
    delivered_total: Decimal
    price_difference: Decimal


class ExchangeDetailOut(BaseModel):
    id: str
    tenant_id: str
    branch_id: str
    original_order_id: str
    original_order_number: Optional[str] = None
    difference_amount: Decimal
    payment_method: str
    cash_received: Optional[Decimal] = None
    cash_returned: Optional[Decimal] = None
    status: str
    notes: Optional[str] = None
    created_at: str
    lines: List[ExchangeLineDetailOut]


class InterbranchTransferIn(BaseModel):
    variant_id: UUID
    from_branch_id: UUID
    to_branch_id: UUID
    quantity: int = Field(..., gt=0, le=500)
    notes: Optional[str] = None


class InterbranchTransferOut(BaseModel):
    variant_id: str
    product_name: str
    size: str
    color: str
    from_branch_id: str
    from_branch_name: str
    to_branch_id: str
    to_branch_name: str
    transferred_quantity: int
    destination_available_stock: int
    message: str


class BranchStockAvailabilityOut(BaseModel):
    branch_id: str
    branch_name: str
    city: str
    address: str
    phone: str
    available_quantity: int
    can_transfer: bool
