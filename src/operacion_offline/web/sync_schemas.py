from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt


OperationType = Literal["SALE", "RESERVATION", "PURCHASE"]
OperationStatus = Literal["CONFIRMED", "CONFLICT", "REJECTED", "UNKNOWN", "RETRY"]
ConflictType = Literal["STOCK", "PRICE", "SUBSCRIPTION", "PRODUCT_INACTIVE"]
ConflictAction = Literal["ADJUST", "AUTHORIZE_PRICE", "CANCEL", "RETRY"]


class OfflineSaleLine(BaseModel):
    variant_id: UUID
    quantity: StrictInt = Field(gt=0, le=10000)
    unit_price: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)


class OfflineSalePayload(BaseModel):
    user_id: UUID | None = None
    customer_id: UUID | None = None
    cash_point_id: UUID | None = None
    items: list[OfflineSaleLine] = Field(min_length=1, max_length=100)
    subtotal: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    total: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    discount_total: Decimal = Field(default=Decimal("0"), ge=0, allow_inf_nan=False)
    cash_received: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    payment_method: Literal["cash"] = "cash"


class OfflinePurchasePayload(BaseModel):
    items: list[OfflineSaleLine] = Field(min_length=1, max_length=100)
    customer_name: str | None = None
    customer_phone: str | None = None
    payment_method: Literal["cash", "stripe", "manual"] = "cash"
    notes: str | None = None


class SyncOperationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_request_id: UUID
    type: OperationType
    branch_id: UUID
    device_id: str = Field(min_length=8, max_length=64)
    client_created_at: datetime
    payload: dict[str, Any]


class SyncBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    client_version: str = Field(max_length=40)
    operations: list[SyncOperationIn] = Field(min_length=1)


class SyncResultOut(BaseModel):
    client_request_id: UUID
    status: OperationStatus
    server_ref: UUID | None = None
    server_number: str | None = None
    conflict_id: UUID | None = None
    conflict_type: str | None = None
    reason_code: str | None = None
    message: str
    replay: bool = False
    refund_amount: str | None = None
    refund_status: Literal['pending','confirmed'] | None = None


class SyncBatchOut(BaseModel):
    batch_id: UUID
    received_at: datetime
    request_id: str | None = None
    results: list[SyncResultOut]


class SyncStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_request_ids: list[UUID] = Field(min_length=1, max_length=200)


class CompetingOperationOut(BaseModel):
    server_number: str
    device_id: str
    synchronized_at: str | datetime
    client_created_at: str | datetime | None = None
    cashier_name: str | None = None
    origin: str | None = None


class ConflictLineOut(BaseModel):
    variant_id: UUID
    product_name: str
    requested_quantity: int
    available_quantity: int
    unit_price: str
    current_price: str
    competing_operation: CompetingOperationOut | None = None


class ConflictOut(BaseModel):
    refund: dict | None = None
    id: UUID
    operation_id: UUID
    client_request_id: UUID
    operation_type: OperationType
    type: str
    status: str
    branch_id: UUID | None = None
    branch_name: str | None = None
    cashier_name: str | None = None
    device_id: str | None = None
    local_folio: str | None = None
    created_at: datetime
    lines: list[ConflictLineOut] = []
    competing_operation: CompetingOperationOut | None = None
    resolution: str | None = None
    resolution_note: str | None = None
    resolved_by_name: str | None = None
    resolved_at: datetime | None = None


class ConflictResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ConflictAction
    quantities: dict[UUID, int] | None = None
    note: str = Field(min_length=5, max_length=300)


class RefundConfirmIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    reference: str = Field(min_length=3, max_length=255)


class SyncBatchLogOut(BaseModel):
    id: UUID
    device_id: str
    user_name: str | None = None
    branch_name: str | None = None
    started_at: datetime
    duration_ms: int
    received: int
    confirmed: int
    conflicts: int
    rejected: int
    replays: int
    error_summary: str | None = None


class SyncOperationSummaryOut(BaseModel):
    client_request_id: UUID
    type: str
    status: str
    reason_code: str | None = None
    conflict_type: str | None = None
    server_number: str | None = None


class SyncBatchDetailOut(SyncBatchLogOut):
    operations: list[SyncOperationSummaryOut] = []
