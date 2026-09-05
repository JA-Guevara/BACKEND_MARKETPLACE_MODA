import uuid
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from src.usuarios_catalogo.infrastructure.models.catalog import ARAssetModel, CategoryModel, CollectionModel, ColorModel, ProductImageModel, ProductModel, ProductVariantModel, SeasonModel, SizeModel


class CatalogRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, entity):
        self.db.add(entity)
        self.db.flush()
        return entity

    def get_category(self, entity_id: uuid.UUID) -> CategoryModel | None:
        return self.db.get(CategoryModel, entity_id)

    def get_size(self, entity_id: uuid.UUID) -> SizeModel | None:
        return self.db.get(SizeModel, entity_id)

    def get_color(self, entity_id: uuid.UUID) -> ColorModel | None:
        return self.db.get(ColorModel, entity_id)

    def get_season(self, entity_id: uuid.UUID) -> SeasonModel | None:
        return self.db.get(SeasonModel, entity_id)

    def get_collection(self, entity_id: uuid.UUID) -> CollectionModel | None:
        return self.db.get(CollectionModel, entity_id)

    def get_product(self, entity_id: uuid.UUID, include_deleted: bool = False) -> ProductModel | None:
        stmt = select(ProductModel).options(
            selectinload(ProductModel.variants),
            selectinload(ProductModel.images),
            selectinload(ProductModel.ar_assets),
            selectinload(ProductModel.suppliers),
        ).where(ProductModel.id == entity_id)
        if not include_deleted:
            stmt = stmt.where(ProductModel.deleted_at.is_(None))
        return self.db.scalar(stmt)

    def get_product_by_slug(self, slug: str, public: bool = True) -> ProductModel | None:
        stmt = select(ProductModel).where(func.lower(ProductModel.slug) == slug.lower(), ProductModel.deleted_at.is_(None))
        if public:
            stmt = stmt.where(ProductModel.is_active.is_(True))
        return self.db.scalar(stmt)

    def find_category_slug(self, slug: str) -> CategoryModel | None:
        return self.db.scalar(select(CategoryModel).where(func.lower(CategoryModel.slug) == slug.lower()))

    def find_size_code(self, code: str) -> SizeModel | None:
        return self.db.scalar(select(SizeModel).where(func.lower(SizeModel.code) == code.lower()))

    def find_color_name(self, name: str) -> ColorModel | None:
        return self.db.scalar(select(ColorModel).where(func.lower(ColorModel.name) == name.lower()))

    def find_color_hex(self, hex_code: str) -> ColorModel | None:
        return self.db.scalar(select(ColorModel).where(func.lower(ColorModel.hex_code) == hex_code.lower()))

    def find_season_name(self, name: str) -> SeasonModel | None:
        return self.db.scalar(select(SeasonModel).where(func.lower(SeasonModel.name) == name.lower()))

    def find_collection(self, name: str, season_id: uuid.UUID | None) -> CollectionModel | None:
        return self.db.scalar(select(CollectionModel).where(func.lower(CollectionModel.name) == name.lower(), CollectionModel.season_id == season_id))

    def find_variant_sku(self, sku: str) -> ProductVariantModel | None:
        return self.db.scalar(select(ProductVariantModel).where(func.lower(ProductVariantModel.sku) == sku.lower()))

    def find_variant_barcode(self, barcode: str) -> ProductVariantModel | None:
        return self.db.scalar(select(ProductVariantModel).where(ProductVariantModel.barcode == barcode))

    def get_variant(self, product_id: uuid.UUID, variant_id: uuid.UUID) -> ProductVariantModel | None:
        return self.db.scalar(select(ProductVariantModel).where(ProductVariantModel.id == variant_id, ProductVariantModel.product_id == product_id))

    def get_image(self, product_id: uuid.UUID, image_id: uuid.UUID) -> ProductImageModel | None:
        return self.db.scalar(select(ProductImageModel).where(ProductImageModel.id == image_id, ProductImageModel.product_id == product_id))

    def get_ar_asset(self, product_id: uuid.UUID, asset_id: uuid.UUID) -> ARAssetModel | None:
        return self.db.scalar(select(ARAssetModel).where(ARAssetModel.id == asset_id, ARAssetModel.product_id == product_id))

    def list_reference(self, model, include_inactive: bool = False):
        stmt = select(model)
        if not include_inactive:
            stmt = stmt.where(model.is_active.is_(True))
        order = model.sort_order if model is SizeModel else model.name
        return list(self.db.scalars(stmt.order_by(order)))

    def list_products(
        self,
        *,
        page: int,
        page_size: int,
        public: bool,
        search: str | None = None,
        category_id: uuid.UUID | None = None,
        season_id: uuid.UUID | None = None,
        collection_id: uuid.UUID | None = None,
        size_id: uuid.UUID | None = None,
        color_id: uuid.UUID | None = None,
        brand: str | None = None,
        featured: bool | None = None,
        min_price: Decimal | None = None,
        max_price: Decimal | None = None,
        include_deleted: bool = False,
    ) -> tuple[list[ProductModel], int]:
        conditions = []
        if not include_deleted:
            conditions.append(ProductModel.deleted_at.is_(None))
        if public:
            conditions.append(ProductModel.is_active.is_(True))
        if search:
            term = f"%{search.strip()}%"
            conditions.append(or_(ProductModel.name.ilike(term), ProductModel.description.ilike(term), ProductModel.brand.ilike(term)))
        if category_id:
            conditions.append(ProductModel.category_id == category_id)
        if season_id:
            conditions.append(ProductModel.season_id == season_id)
        if collection_id:
            conditions.append(ProductModel.collection_id == collection_id)
        if brand:
            conditions.append(ProductModel.brand.ilike(brand.strip()))
        if featured is not None:
            conditions.append(ProductModel.is_featured == featured)
        if min_price is not None:
            conditions.append(ProductModel.base_price >= min_price)
        if max_price is not None:
            conditions.append(ProductModel.base_price <= max_price)
        stmt = select(ProductModel).where(*conditions)
        count_stmt = select(func.count(func.distinct(ProductModel.id))).where(*conditions)
        if size_id or color_id:
            variant_conditions = [ProductVariantModel.is_active.is_(True)]
            if size_id:
                variant_conditions.append(ProductVariantModel.size_id == size_id)
            if color_id:
                variant_conditions.append(ProductVariantModel.color_id == color_id)
            stmt = stmt.join(ProductModel.variants).where(*variant_conditions)
            count_stmt = count_stmt.join(ProductModel.variants).where(*variant_conditions)
            stmt = stmt.distinct()
        total = self.db.scalar(count_stmt) or 0
        items = list(self.db.scalars(stmt.order_by(ProductModel.is_featured.desc(), ProductModel.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).unique())
        return items, total
