from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime, timezone
from math import ceil

from sqlalchemy import String, cast, func, select, update
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.infrastructure.database.base import Base
from src.inventario_sucursales.infrastructure.models.organization import SupplierModel
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError, ValidationError
from src.shared.responses.pagination import Page
from src.usuarios_catalogo.infrastructure.models.catalog import ARAssetModel, CategoryModel, CollectionModel, ColorModel, ProductImageModel, ProductModel, ProductSupplierModel, ProductVariantModel, SeasonModel, SizeModel
from src.usuarios_catalogo.infrastructure.repositories.catalog_repository import CatalogRepository
from src.usuarios_catalogo.web.schemas.catalog import ARAssetCreate, ARAssetUpdate, CategoryCreate, CategoryUpdate, CollectionCreate, CollectionUpdate, ColorCreate, ColorUpdate, ImageCreate, ProductCreate, ProductSupplierInput, ProductUpdate, PublicProductResponse, SeasonCreate, SeasonUpdate, SizeCreate, SizeUpdate, VariantCreate, VariantUpdate


class CatalogService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = CatalogRepository(db)
        self.audit = RecordAuditEvent(db)

    def create_category(self, data: CategoryCreate, actor: UserModel) -> CategoryModel:
        slug = self._unique_slug(data.slug or data.name, CategoryModel)
        if data.parent_id:
            self.require_reference(CategoryModel, data.parent_id)
        entity = CategoryModel(name=data.name.strip(), slug=slug, description=data.description, parent_id=data.parent_id)
        return self._save_created(entity, actor, "catalog.category_created", "Categoria creada.")

    def update_category(self, entity_id: uuid.UUID, data: CategoryUpdate, actor: UserModel) -> CategoryModel:
        entity = self.require_reference(CategoryModel, entity_id)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("parent_id"):
            parent_id = changes["parent_id"]
            seen = {entity.id}
            while parent_id:
                if parent_id in seen:
                    raise ValidationError("La categoria superior no puede crear un ciclo en la jerarquia.")
                seen.add(parent_id)
                parent_id = self.require_reference(CategoryModel, parent_id).parent_id
        if "slug" in changes:
            source = changes.get("slug") or entity.slug
            changes["slug"] = self._unique_slug(source, CategoryModel, entity.id)
        return self._save_updated(entity, changes, actor, "catalog.category_updated", "Categoria actualizada.")

    def create_size(self, data: SizeCreate, actor: UserModel) -> SizeModel:
        code = data.code.strip().upper()
        if self.repository.find_size_code(code):
            raise ConflictError("El codigo de talla ya existe.")
        return self._save_created(SizeModel(code=code, name=data.name.strip(), sort_order=data.sort_order), actor, "catalog.size_created", "Talla creada.")

    def update_size(self, entity_id: uuid.UUID, data: SizeUpdate, actor: UserModel) -> SizeModel:
        entity = self.require_reference(SizeModel, entity_id)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("code"):
            changes["code"] = changes["code"].strip().upper()
            duplicate = self.repository.find_size_code(changes["code"])
            if duplicate and duplicate.id != entity.id:
                raise ConflictError("El codigo de talla ya existe.")
        return self._save_updated(entity, changes, actor, "catalog.size_updated", "Talla actualizada.")

    def create_color(self, data: ColorCreate, actor: UserModel) -> ColorModel:
        self._validate_color_unique(data.name, data.hex_code)
        return self._save_created(ColorModel(name=data.name.strip(), hex_code=data.hex_code.upper()), actor, "catalog.color_created", "Color creado.")

    def update_color(self, entity_id: uuid.UUID, data: ColorUpdate, actor: UserModel) -> ColorModel:
        entity = self.require_reference(ColorModel, entity_id)
        changes = data.model_dump(exclude_unset=True)
        if changes:
            self._validate_color_unique(changes.get("name", entity.name), changes.get("hex_code", entity.hex_code), entity.id)
        if changes.get("hex_code"):
            changes["hex_code"] = changes["hex_code"].upper()
        return self._save_updated(entity, changes, actor, "catalog.color_updated", "Color actualizado.")

    def create_season(self, data: SeasonCreate, actor: UserModel) -> SeasonModel:
        if self.repository.find_season_name(data.name):
            raise ConflictError("La temporada ya existe.")
        return self._save_created(SeasonModel(**self._trimmed(data.model_dump())), actor, "catalog.season_created", "Temporada creada.")

    def update_season(self, entity_id: uuid.UUID, data: SeasonUpdate, actor: UserModel) -> SeasonModel:
        entity = self.require_reference(SeasonModel, entity_id)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("name"):
            duplicate = self.repository.find_season_name(changes["name"])
            if duplicate and duplicate.id != entity.id:
                raise ConflictError("La temporada ya existe.")
        start = changes.get("start_date", entity.start_date)
        end = changes.get("end_date", entity.end_date)
        if start and end and end < start:
            raise ValidationError("La fecha final no puede ser anterior a la fecha inicial.")
        return self._save_updated(entity, changes, actor, "catalog.season_updated", "Temporada actualizada.")

    def create_collection(self, data: CollectionCreate, actor: UserModel) -> CollectionModel:
        if data.season_id:
            self.require_reference(SeasonModel, data.season_id, active=True)
        if self.repository.find_collection(data.name, data.season_id):
            raise ConflictError("La coleccion ya existe para esa temporada.")
        return self._save_created(CollectionModel(**self._trimmed(data.model_dump())), actor, "catalog.collection_created", "Coleccion creada.")

    def update_collection(self, entity_id: uuid.UUID, data: CollectionUpdate, actor: UserModel) -> CollectionModel:
        entity = self.require_reference(CollectionModel, entity_id)
        changes = data.model_dump(exclude_unset=True)
        season_id = changes.get("season_id", entity.season_id)
        if season_id:
            self.require_reference(SeasonModel, season_id, active=True)
        name = changes.get("name", entity.name)
        duplicate = self.repository.find_collection(name, season_id)
        if duplicate and duplicate.id != entity.id:
            raise ConflictError("La coleccion ya existe para esa temporada.")
        return self._save_updated(entity, changes, actor, "catalog.collection_updated", "Coleccion actualizada.")

    def set_reference_active(self, model, entity_id: uuid.UUID, active: bool, actor: UserModel):
        entity = self.require_reference(model, entity_id)
        if not active:
            self._ensure_reference_unused(entity)
        entity.is_active = active
        self._audit(actor, "catalog.reference_status_changed", entity, "Estado de dato de catalogo actualizado.")
        self.db.commit()
        return entity

    def delete_reference(self, model, entity_id: uuid.UUID, actor: UserModel) -> None:
        entity = self.require_reference(model, entity_id)
        self._ensure_reference_unused(entity)
        self._audit(actor, "catalog.reference_deleted", entity, "Dato de catalogo eliminado.")
        self.db.delete(entity)
        self.db.commit()

    def create_product(self, data: ProductCreate, actor: UserModel) -> ProductModel:
        self._validate_product_references(data.category_id, data.season_id, data.collection_id)
        slug = self._unique_slug(data.slug or data.name, ProductModel)
        self._validate_primary_flags(data.images, "imagenes")
        self._validate_primary_flags(data.suppliers, "proveedores")
        product = ProductModel(
            name=data.name.strip(), slug=slug, description=data.description.strip(), brand=self._strip(data.brand),
            gender=self._strip(data.gender), base_price=data.base_price, category_id=data.category_id,
            season_id=data.season_id, collection_id=data.collection_id, is_featured=data.is_featured,
        )
        self.repository.add(product)
        seen_combinations: set[tuple[uuid.UUID, uuid.UUID]] = set()
        for variant_data in data.variants:
            combination = (variant_data.size_id, variant_data.color_id)
            if combination in seen_combinations:
                raise ConflictError("No se puede repetir la misma combinacion de talla y color.")
            seen_combinations.add(combination)
            product.variants.append(self._build_variant(variant_data))
        for image_data in data.images:
            product.images.append(self._build_image(image_data))
        product.suppliers = self._build_supplier_links(data.suppliers)
        self._audit(actor, "catalog.product_created", product, "Producto creado.")
        self.db.commit()
        return self.repository.get_product(product.id) or product

    def update_product(self, entity_id: uuid.UUID, data: ProductUpdate, actor: UserModel) -> ProductModel:
        product = self.require_product(entity_id)
        changes = data.model_dump(exclude_unset=True)
        changes.pop("images", None)
        if data.images is not None:
            self._validate_primary_flags(data.images, "imagenes")
            existing_images = {image.id: image for image in product.images}
            ids = [image.id for image in data.images if image.id]
            if len(ids) != len(set(ids)) or any(image_id not in existing_images for image_id in ids):
                raise ValidationError("Las imagenes deben pertenecer a esta prenda y no repetirse.")
            gallery = []
            for image_data in data.images:
                image = existing_images.get(image_data.id) if image_data.id else self._build_image(image_data)
                image.url = str(image_data.url)
                image.alt_text = image_data.alt_text
                image.sort_order = image_data.sort_order
                image.is_primary = image_data.is_primary
                gallery.append(image)
            product.images = gallery
        category_id = changes.get("category_id", product.category_id)
        season_id = changes.get("season_id", product.season_id)
        collection_id = changes.get("collection_id", product.collection_id)
        self._validate_product_references(category_id, season_id, collection_id)
        if "slug" in changes:
            source = changes.get("slug") or product.slug
            changes["slug"] = self._unique_slug(source, ProductModel, product.id)
        product = self._save_updated(product, changes, actor, "catalog.product_updated", "Producto actualizado.")
        return self.repository.get_product(product.id) or product

    def set_product_active(self, entity_id: uuid.UUID, active: bool, actor: UserModel) -> ProductModel:
        product = self.require_product(entity_id, include_deleted=True)
        product.is_active = active
        if active:
            product.deleted_at = None
        self._audit(actor, "catalog.product_status_changed", product, "Estado de producto actualizado.")
        self.db.commit()
        return self.repository.get_product(product.id, include_deleted=True) or product

    def delete_product(self, entity_id: uuid.UUID, actor: UserModel) -> None:
        product = self.require_product(entity_id)
        product.is_active = False
        product.deleted_at = datetime.now(timezone.utc)
        self._audit(actor, "catalog.product_deleted", product, "Producto eliminado logicamente.")
        self.db.commit()

    def add_variant(self, product_id: uuid.UUID, data: VariantCreate, actor: UserModel) -> ProductModel:
        product = self.require_product(product_id)
        if any(item.size_id == data.size_id and item.color_id == data.color_id for item in product.variants):
            raise ConflictError("La variante de talla y color ya existe.")
        product.variants.append(self._build_variant(data))
        self._audit(actor, "catalog.variant_created", product, "Variante agregada.")
        self.db.commit()
        return self.repository.get_product(product.id) or product

    def update_variant(self, product_id: uuid.UUID, variant_id: uuid.UUID, data: VariantUpdate, actor: UserModel) -> ProductModel:
        product = self.require_product(product_id)
        variant = self.repository.get_variant(product_id, variant_id)
        if not variant:
            raise NotFoundError("Variante no encontrada.")
        changes = data.model_dump(exclude_unset=True)
        size_id = changes.get("size_id", variant.size_id)
        color_id = changes.get("color_id", variant.color_id)
        if changes.get("sku"):
            changes["sku"] = changes["sku"].strip().upper()
        if "barcode" in changes:
            changes["barcode"] = self._strip(changes["barcode"])
        self._validate_variant_references(size_id, color_id)
        if any(item.id != variant.id and item.size_id == size_id and item.color_id == color_id for item in product.variants):
            raise ConflictError("La variante de talla y color ya existe.")
        self._validate_variant_identity(changes.get("sku", variant.sku), changes.get("barcode", variant.barcode), variant.id)
        self._update(variant, changes)
        self._audit(actor, "catalog.variant_updated", variant, "Variante actualizada.")
        self.db.commit()
        return self.repository.get_product(product.id) or product

    def delete_variant(self, product_id: uuid.UUID, variant_id: uuid.UUID, actor: UserModel) -> ProductModel:
        product = self.require_product(product_id)
        variant = self.repository.get_variant(product_id, variant_id)
        if not variant:
            raise NotFoundError("Variante no encontrada.")
        # A variant is the identity used by stock, carts and the movement ledger.
        # Keep every referencing row intact; historical snapshots also retain it.
        for table in Base.metadata.tables.values():
            for column in table.columns:
                if any(fk.target_fullname == "product_variants.id" for fk in column.foreign_keys):
                    if self.db.scalar(select(column).where(column == variant_id).limit(1)) is not None:
                        raise ConflictError("La variante tiene existencias, movimientos o carritos asociados. Desactivala desde Editar para conservar el historial.")
        for table_name in ("commerce_orders", "reservations"):
            table = Base.metadata.tables.get(table_name)
            if table is not None and self.db.scalar(
                select(table.c.id).where(cast(table.c["items"], String).contains(str(variant_id))).limit(1)
            ) is not None:
                raise ConflictError("La variante tiene pedidos o reservas asociados. Desactivala desde Editar para conservar el historial.")
        self._audit(actor, "catalog.variant_deleted", variant, "Variante eliminada.")
        self.db.delete(variant)
        self.db.commit()
        return self.repository.get_product(product.id) or product

    def add_image(self, product_id: uuid.UUID, data: ImageCreate, actor: UserModel) -> ProductModel:
        product = self.require_product(product_id)
        if data.is_primary:
            self.db.execute(update(ProductImageModel).where(ProductImageModel.product_id == product_id).values(is_primary=False))
        image = self._build_image(data)
        product.images.append(image)
        self._audit(actor, "catalog.image_created", product, "Imagen agregada.")
        self.db.commit()
        return self.repository.get_product(product.id) or product

    def delete_image(self, product_id: uuid.UUID, image_id: uuid.UUID, actor: UserModel) -> ProductModel:
        product = self.require_product(product_id)
        image = self.repository.get_image(product_id, image_id)
        if not image:
            raise NotFoundError("Imagen no encontrada.")
        self._audit(actor, "catalog.image_deleted", image, "Imagen eliminada.")
        self.db.delete(image)
        self.db.commit()
        return self.repository.get_product(product.id) or product

    def add_ar_asset(self, product_id: uuid.UUID, data: ARAssetCreate, actor: UserModel) -> ProductModel:
        product = self.require_product(product_id)
        asset = ARAssetModel(product_id=product_id, asset_type=data.asset_type, asset_url=str(data.asset_url), preview_url=str(data.preview_url) if data.preview_url else None)
        self.repository.add(asset)
        self._audit(actor, "catalog.ar_asset_created", asset, "Activo de realidad aumentada agregado.")
        self.db.commit()
        return self.repository.get_product(product.id) or product

    def delete_ar_asset(self, product_id: uuid.UUID, asset_id: uuid.UUID, actor: UserModel) -> ProductModel:
        product = self.require_product(product_id)
        asset = self.repository.get_ar_asset(product_id, asset_id)
        if not asset:
            raise NotFoundError("Activo de realidad aumentada no encontrado.")
        self._audit(actor, "catalog.ar_asset_deleted", asset, "Activo de realidad aumentada eliminado.")
        self.db.delete(asset)
        self.db.commit()
        return self.repository.get_product(product.id) or product

    def update_ar_asset(self, product_id: uuid.UUID, asset_id: uuid.UUID, data: ARAssetUpdate, actor: UserModel) -> ProductModel:
        """Edita un recurso AR: puede corregir tipo/URLs y activarlo como el
        recurso por defecto de su tipo (los demás del mismo tipo quedan
        inactivos para que el probador sepa cuál usar)."""
        product = self.require_product(product_id)
        asset = self.repository.get_ar_asset(product_id, asset_id)
        if not asset:
            raise NotFoundError("Activo de realidad aumentada no encontrado.")
        changes = {}
        if data.asset_type is not None:
            changes["asset_type"] = data.asset_type
        if data.asset_url is not None:
            changes["asset_url"] = str(data.asset_url)
        if data.preview_url is not None:
            changes["preview_url"] = str(data.preview_url)
        if data.is_active is True:
            self.db.execute(
                update(ARAssetModel)
                .where(ARAssetModel.product_id == product_id, ARAssetModel.id != asset_id)
                .values(is_active=False)
            )
            changes["is_active"] = True
        elif data.is_active is False:
            changes["is_active"] = False
        for key, value in changes.items():
            setattr(asset, key, value)
        self._audit(actor, "catalog.ar_asset_updated", asset, "Activo de realidad aumentada actualizado.")
        self.db.commit()
        return self.repository.get_product(product.id) or product

    def set_suppliers(self, product_id: uuid.UUID, suppliers: list[ProductSupplierInput], actor: UserModel) -> ProductModel:
        product = self.require_product(product_id)
        self._validate_primary_flags(suppliers, "proveedores")
        validated = self._build_supplier_links(suppliers)
        existing = {link.supplier_id: link for link in product.suppliers}
        links = []
        for incoming in validated:
            link = existing.get(incoming.supplier_id, incoming)
            link.supplier_sku = incoming.supplier_sku
            link.unit_cost = incoming.unit_cost
            link.is_primary = incoming.is_primary
            links.append(link)
        product.suppliers = links
        self._audit(actor, "catalog.product_suppliers_updated", product, "Proveedores del producto actualizados.")
        self.db.commit()
        return self.repository.get_product(product.id) or product

    def public_page(self, **filters) -> Page[PublicProductResponse]:
        items, total = self.repository.list_products(public=True, **filters)
        public_items = [self.to_public(item) for item in items]
        return Page(items=public_items, total=total, page=filters["page"], page_size=filters["page_size"], pages=ceil(total / filters["page_size"]) if total else 0)

    @staticmethod
    def to_public(product: ProductModel) -> PublicProductResponse:
        return PublicProductResponse.model_validate({
            "id": product.id, "name": product.name, "slug": product.slug, "description": product.description,
            "brand": product.brand, "gender": product.gender, "base_price": product.base_price,
            "category": product.category, "season": product.season, "collection": product.collection,
            "is_featured": product.is_featured, "variants": [item for item in product.variants if item.is_active],
            "images": product.images, "ar_assets": [item for item in product.ar_assets if item.is_active],
        })

    def require_reference(self, model, entity_id: uuid.UUID, active: bool = False):
        getters = {CategoryModel: self.repository.get_category, SizeModel: self.repository.get_size, ColorModel: self.repository.get_color, SeasonModel: self.repository.get_season, CollectionModel: self.repository.get_collection}
        entity = getters[model](entity_id)
        if not entity:
            raise NotFoundError("Dato de catalogo no encontrado.")
        if active and not entity.is_active:
            raise ConflictError("El dato de catalogo seleccionado esta inactivo.")
        return entity

    def require_product(self, entity_id: uuid.UUID, include_deleted: bool = False) -> ProductModel:
        product = self.repository.get_product(entity_id, include_deleted)
        if not product:
            raise NotFoundError("Producto no encontrado.")
        return product

    def _build_variant(self, data: VariantCreate) -> ProductVariantModel:
        self._validate_variant_references(data.size_id, data.color_id)
        self._validate_variant_identity(data.sku, data.barcode)
        return ProductVariantModel(size_id=data.size_id, color_id=data.color_id, sku=data.sku.strip().upper(), barcode=self._strip(data.barcode), price_override=data.price_override)

    def _build_image(self, data: ImageCreate) -> ProductImageModel:
        return ProductImageModel(url=str(data.url), alt_text=data.alt_text, sort_order=data.sort_order, is_primary=data.is_primary)

    def _build_supplier_links(self, suppliers: list[ProductSupplierInput]) -> list[ProductSupplierModel]:
        seen: set[uuid.UUID] = set()
        links = []
        for item in suppliers:
            if item.supplier_id in seen:
                raise ConflictError("No se puede repetir un proveedor en el producto.")
            seen.add(item.supplier_id)
            supplier = self.db.get(SupplierModel, item.supplier_id)
            if not supplier or not supplier.is_active or supplier.deleted_at:
                raise NotFoundError("Uno de los proveedores no existe o esta inactivo.")
            links.append(ProductSupplierModel(**item.model_dump()))
        return links

    def _validate_product_references(self, category_id, season_id, collection_id) -> None:
        self.require_reference(CategoryModel, category_id, active=True)
        if season_id:
            self.require_reference(SeasonModel, season_id, active=True)
        if collection_id:
            collection = self.require_reference(CollectionModel, collection_id, active=True)
            if season_id and collection.season_id and collection.season_id != season_id:
                raise ValidationError("La coleccion no pertenece a la temporada seleccionada.")

    def _validate_variant_references(self, size_id: uuid.UUID, color_id: uuid.UUID) -> None:
        self.require_reference(SizeModel, size_id, active=True)
        self.require_reference(ColorModel, color_id, active=True)

    def _validate_variant_identity(self, sku: str, barcode: str | None, current_id: uuid.UUID | None = None) -> None:
        existing = self.repository.find_variant_sku(sku)
        if existing and existing.id != current_id:
            raise ConflictError("El SKU de variante ya existe.")
        if barcode:
            existing = self.repository.find_variant_barcode(barcode)
            if existing and existing.id != current_id:
                raise ConflictError("El codigo de barras ya existe.")

    def _validate_color_unique(self, name: str, hex_code: str, current_id: uuid.UUID | None = None) -> None:
        for existing in (self.repository.find_color_name(name), self.repository.find_color_hex(hex_code)):
            if existing and existing.id != current_id:
                raise ConflictError("El nombre o codigo hexadecimal del color ya existe.")

    def _ensure_reference_unused(self, entity) -> None:
        checks = {
            CategoryModel: [(ProductModel, ProductModel.category_id), (CategoryModel, CategoryModel.parent_id)],
            SizeModel: [(ProductVariantModel, ProductVariantModel.size_id)],
            ColorModel: [(ProductVariantModel, ProductVariantModel.color_id)],
            SeasonModel: [(ProductModel, ProductModel.season_id), (CollectionModel, CollectionModel.season_id)],
            CollectionModel: [(ProductModel, ProductModel.collection_id)],
        }
        for model, column in checks[type(entity)]:
            if self.db.scalar(select(func.count(model.id)).where(column == entity.id)):
                raise ConflictError("No se puede modificar el estado o eliminar porque tiene registros asociados.")

    def _unique_slug(self, value: str, model, current_id: uuid.UUID | None = None) -> str:
        base = self._slugify(value)
        if not base:
            raise ValidationError("No se pudo generar un slug valido.")
        slug = base
        counter = 2
        while True:
            column = model.slug
            existing = self.db.scalar(select(model).where(func.lower(column) == slug.lower()))
            if not existing or existing.id == current_id:
                return slug
            slug = f"{base}-{counter}"
            counter += 1

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
        return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")

    @staticmethod
    def _validate_primary_flags(items: list, label: str) -> None:
        if sum(bool(item.is_primary) for item in items) > 1:
            raise ValidationError(f"Solo puede existir un elemento principal en {label}.")

    def _save_created(self, entity, actor: UserModel, action: str, description: str):
        self.repository.add(entity)
        self._audit(actor, action, entity, description)
        self.db.commit()
        self.db.refresh(entity)
        return entity

    def _save_updated(self, entity, changes: dict, actor: UserModel, action: str, description: str):
        self._update(entity, changes)
        self._audit(actor, action, entity, description)
        self.db.commit()
        return entity

    def _update(self, entity, changes: dict) -> None:
        for field, value in self._trimmed(changes).items():
            setattr(entity, field, value)

    @staticmethod
    def _trimmed(values: dict) -> dict:
        return {key: value.strip() if isinstance(value, str) else value for key, value in values.items()}

    @staticmethod
    def _strip(value: str | None) -> str | None:
        return value.strip() if value else None

    def _audit(self, actor: UserModel, action: str, entity, description: str) -> None:
        self.audit.execute(actor_user_id=actor.id, action=action, entity_type=entity.__tablename__, entity_id=str(entity.id), description=description)
