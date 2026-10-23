from datetime import datetime
from decimal import Decimal
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from src.auth.infrastructure.http.schemas import TenantSummary


class SnapshotBranch(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    address: str


class SnapshotProduct(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str
    category: str
    brand: str | None
    base_price: Decimal
    offer_price: Decimal | None
    image_url: str | None
    is_featured: bool


class SnapshotVariant(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    product_id: UUID
    sku: str
    size: str
    color: str
    color_hex: str
    price: Decimal | None
    is_active: bool


class SnapshotStock(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    variant_id: UUID
    branch_id: UUID
    quantity: int


class SnapshotCustomer(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    document_tail: str | None
    phone: str | None


class SnapshotRemoved(BaseModel):
    products: list[UUID]
    variants: list[UUID]


class OfflineSnapshot(BaseModel):
    version: str
    generated_at: datetime
    full: bool
    tenant: TenantSummary
    branches: list[SnapshotBranch]
    products: list[SnapshotProduct]
    variants: list[SnapshotVariant]
    stock: list[SnapshotStock]
    customers: list[SnapshotCustomer]
    removed: SnapshotRemoved
