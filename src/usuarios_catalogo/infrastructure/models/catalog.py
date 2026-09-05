import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CategoryModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("slug"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(140), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SizeModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sizes"
    __table_args__ = (UniqueConstraint("code"),)

    code: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ColorModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "colors"
    __table_args__ = (UniqueConstraint("name"), UniqueConstraint("hex_code"))

    name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    hex_code: Mapped[str] = mapped_column(String(7), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SeasonModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CollectionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "collections"
    __table_args__ = (UniqueConstraint("name", "season_id"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    season_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("seasons.id", ondelete="RESTRICT"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    season: Mapped[SeasonModel | None] = relationship(lazy="joined")


class ProductModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("slug"),
        CheckConstraint("base_price >= 0", name="base_price_nonnegative"),
    )

    name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(String(100), index=True)
    gender: Mapped[str | None] = mapped_column(String(30), index=True)
    base_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False, index=True)
    season_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("seasons.id", ondelete="RESTRICT"), index=True)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collections.id", ondelete="RESTRICT"), index=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    category: Mapped[CategoryModel] = relationship(lazy="joined")
    season: Mapped[SeasonModel | None] = relationship(lazy="joined")
    collection: Mapped[CollectionModel | None] = relationship(lazy="joined")
    variants: Mapped[list["ProductVariantModel"]] = relationship(back_populates="product", cascade="all, delete-orphan", lazy="selectin")
    images: Mapped[list["ProductImageModel"]] = relationship(back_populates="product", cascade="all, delete-orphan", lazy="selectin", order_by="ProductImageModel.sort_order")
    ar_assets: Mapped[list["ARAssetModel"]] = relationship(back_populates="product", cascade="all, delete-orphan", lazy="selectin")
    suppliers: Mapped[list["ProductSupplierModel"]] = relationship(back_populates="product", cascade="all, delete-orphan", lazy="selectin")


class ProductVariantModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("product_id", "size_id", "color_id"),
        UniqueConstraint("sku"),
        UniqueConstraint("barcode"),
        CheckConstraint("price_override IS NULL OR price_override >= 0", name="price_override_nonnegative"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    size_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sizes.id", ondelete="RESTRICT"), nullable=False, index=True)
    color_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("colors.id", ondelete="RESTRICT"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    barcode: Mapped[str | None] = mapped_column(String(80), index=True)
    price_override: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    product: Mapped[ProductModel] = relationship(back_populates="variants")
    size: Mapped[SizeModel] = relationship(lazy="joined")
    color: Mapped[ColorModel] = relationship(lazy="joined")


class ProductImageModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_images"

    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    alt_text: Mapped[str | None] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    product: Mapped[ProductModel] = relationship(back_populates="images")


class ARAssetModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ar_assets"

    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False)
    asset_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    preview_url: Mapped[str | None] = mapped_column(String(1000))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    product: Mapped[ProductModel] = relationship(back_populates="ar_assets")


class ProductSupplierModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_suppliers"
    __table_args__ = (UniqueConstraint("product_id", "supplier_id"), CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="unit_cost_nonnegative"))

    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)
    supplier_sku: Mapped[str | None] = mapped_column(String(100))
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    product: Mapped[ProductModel] = relationship(back_populates="suppliers")
