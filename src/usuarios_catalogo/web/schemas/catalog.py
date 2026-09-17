import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class CatalogInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class ProductDraftRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    message: str = Field(min_length=3, max_length=500)


class CategoryCreate(CatalogInput):
    name: str = Field(min_length=2, max_length=120)
    slug: str | None = Field(default=None, max_length=140)
    description: str | None = None
    parent_id: uuid.UUID | None = None


class CategoryUpdate(CatalogInput):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    slug: str | None = Field(default=None, max_length=140)
    description: str | None = None
    parent_id: uuid.UUID | None = None


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    parent_id: uuid.UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SizeCreate(CatalogInput):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=80)
    sort_order: int = Field(default=0, ge=0)


class SizeUpdate(CatalogInput):
    code: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    sort_order: int | None = Field(default=None, ge=0)


class SizeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ColorCreate(CatalogInput):
    name: str = Field(min_length=2, max_length=80)
    hex_code: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class ColorUpdate(CatalogInput):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    hex_code: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class ColorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    hex_code: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SeasonCreate(CatalogInput):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class SeasonUpdate(SeasonCreate):
    name: str | None = Field(default=None, min_length=2, max_length=120)


class SeasonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    start_date: date | None
    end_date: date | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CollectionCreate(CatalogInput):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    season_id: uuid.UUID | None = None


class CollectionUpdate(CatalogInput):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    season_id: uuid.UUID | None = None


class CollectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    season_id: uuid.UUID | None
    season: SeasonResponse | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class VariantCreate(CatalogInput):
    size_id: uuid.UUID
    color_id: uuid.UUID
    sku: str = Field(min_length=2, max_length=80)
    barcode: str | None = Field(default=None, max_length=80)
    price_override: Decimal | None = Field(default=None, ge=0)


class VariantUpdate(CatalogInput):
    size_id: uuid.UUID | None = None
    color_id: uuid.UUID | None = None
    sku: str | None = Field(default=None, min_length=2, max_length=80)
    barcode: str | None = Field(default=None, max_length=80)
    price_override: Decimal | None = Field(default=None, ge=0)
    is_active: bool | None = None


class VariantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    size_id: uuid.UUID
    color_id: uuid.UUID
    size: SizeResponse
    color: ColorResponse
    sku: str
    barcode: str | None
    price_override: Decimal | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ImageCreate(CatalogInput):
    url: HttpUrl
    alt_text: str | None = Field(default=None, max_length=255)
    sort_order: int = Field(default=0, ge=0)
    is_primary: bool = False


class ImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    url: str
    alt_text: str | None
    sort_order: int
    is_primary: bool


class ARAssetCreate(BaseModel):
    asset_type: str = Field(pattern=r"^(image_overlay|glb|gltf|usdz)$")
    asset_url: HttpUrl
    preview_url: HttpUrl | None = None


class ARAssetUpdate(BaseModel):
    """Editacion de un recurso AR existente: se pueden corregir las URLs o
    activarlo/desactivarlo como recurso por defecto del probador. Campo por
    campo, sin tocar los que no llegan."""
    asset_type: str | None = Field(default=None, pattern=r"^(image_overlay|glb|gltf|usdz)$")
    asset_url: HttpUrl | None = None
    preview_url: HttpUrl | None = None
    is_active: bool | None = None


class ARAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    asset_type: str
    asset_url: str
    preview_url: str | None
    is_active: bool


class ProductSupplierInput(CatalogInput):
    supplier_id: uuid.UUID
    supplier_sku: str | None = Field(default=None, max_length=100)
    unit_cost: Decimal | None = Field(default=None, ge=0)
    is_primary: bool = False


class ProductSupplierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_sku: str | None
    unit_cost: Decimal | None
    is_primary: bool


class ProductCreate(CatalogInput):
    name: str = Field(min_length=2, max_length=180)
    slug: str | None = Field(default=None, max_length=200)
    description: str = Field(min_length=5)
    brand: str | None = Field(default=None, max_length=100)
    gender: str | None = Field(default=None, max_length=30)
    base_price: Decimal = Field(ge=0)
    category_id: uuid.UUID
    season_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
    is_featured: bool = False
    variants: list[VariantCreate] = Field(default_factory=list)
    images: list[ImageCreate] = Field(default_factory=list)
    suppliers: list[ProductSupplierInput] = Field(default_factory=list)


class ImageEdit(ImageCreate):
    id: uuid.UUID | None = None


class ProductUpdate(CatalogInput):
    images: list[ImageEdit] | None = None
    name: str | None = Field(default=None, min_length=2, max_length=180)
    slug: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, min_length=5)
    brand: str | None = Field(default=None, max_length=100)
    gender: str | None = Field(default=None, max_length=30)
    base_price: Decimal | None = Field(default=None, ge=0)
    category_id: uuid.UUID | None = None
    season_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
    is_featured: bool | None = None


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str
    brand: str | None
    gender: str | None
    base_price: Decimal
    category_id: uuid.UUID
    category: CategoryResponse
    season_id: uuid.UUID | None
    season: SeasonResponse | None
    collection_id: uuid.UUID | None
    collection: CollectionResponse | None
    is_featured: bool
    is_active: bool
    deleted_at: datetime | None
    variants: list[VariantResponse] = Field(default_factory=list)
    images: list[ImageResponse] = Field(default_factory=list)
    ar_assets: list[ARAssetResponse] = Field(default_factory=list)
    suppliers: list[ProductSupplierResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PublicProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str
    brand: str | None
    gender: str | None
    base_price: Decimal
    category: CategoryResponse
    season: SeasonResponse | None
    collection: CollectionResponse | None
    is_featured: bool
    variants: list[VariantResponse] = Field(default_factory=list)
    images: list[ImageResponse] = Field(default_factory=list)
    ar_assets: list[ARAssetResponse] = Field(default_factory=list)


class SetProductSuppliersRequest(BaseModel):
    suppliers: list[ProductSupplierInput]
