import uuid
from decimal import Decimal
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.shared.exceptions.domain_exception import NotFoundError
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page
from src.usuarios_catalogo.application.services.catalog_service import CatalogService
from src.usuarios_catalogo.infrastructure.models.catalog import CategoryModel, CollectionModel, ColorModel, ProductModel, SeasonModel, SizeModel
from src.usuarios_catalogo.infrastructure.repositories.catalog_repository import CatalogRepository
from src.usuarios_catalogo.web.schemas.catalog import ARAssetCreate, CategoryCreate, CategoryResponse, CategoryUpdate, CollectionCreate, CollectionResponse, CollectionUpdate, ColorCreate, ColorResponse, ColorUpdate, ImageCreate, ProductCreate, ProductResponse, ProductUpdate, PublicProductResponse, SeasonCreate, SeasonResponse, SeasonUpdate, SetProductSuppliersRequest, SizeCreate, SizeResponse, SizeUpdate, VariantCreate, VariantUpdate


router = APIRouter(prefix="/catalog", tags=["catalog"])
CatalogReader = Annotated[UserModel, Depends(require_permissions("catalog.read"))]
CatalogWriter = Annotated[UserModel, Depends(require_permissions("catalog.write"))]


@router.get("/products", response_model=ApiResponse[Page[PublicProductResponse]], tags=["public catalog"])
def public_products(
    db: Session = Depends(get_db), page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100),
    search: str | None = None, category_id: uuid.UUID | None = None, season_id: uuid.UUID | None = None,
    collection_id: uuid.UUID | None = None, size_id: uuid.UUID | None = None, color_id: uuid.UUID | None = None,
    brand: str | None = None, featured: bool | None = None, min_price: Decimal | None = Query(default=None, ge=0),
    max_price: Decimal | None = Query(default=None, ge=0),
):
    result = CatalogService(db).public_page(
        page=page, page_size=page_size, search=search, category_id=category_id, season_id=season_id,
        collection_id=collection_id, size_id=size_id, color_id=color_id, brand=brand, featured=featured,
        min_price=min_price, max_price=max_price, include_deleted=False,
    )
    return ApiResponse(message="Catalogo obtenido.", data=result)


@router.get("/products/{slug}", response_model=ApiResponse[PublicProductResponse], tags=["public catalog"])
def public_product(slug: str, db: Session = Depends(get_db)):
    product = CatalogRepository(db).get_product_by_slug(slug)
    if not product:
        raise NotFoundError("Producto no encontrado.")
    return ApiResponse(message="Producto obtenido.", data=CatalogService.to_public(product))


@router.get("/categories", response_model=ApiResponse[list[CategoryResponse]], tags=["public catalog"])
def public_categories(db: Session = Depends(get_db)):
    return ApiResponse(message="Categorias obtenidas.", data=CatalogRepository(db).list_reference(CategoryModel))


@router.get("/sizes", response_model=ApiResponse[list[SizeResponse]], tags=["public catalog"])
def public_sizes(db: Session = Depends(get_db)):
    return ApiResponse(message="Tallas obtenidas.", data=CatalogRepository(db).list_reference(SizeModel))


@router.get("/colors", response_model=ApiResponse[list[ColorResponse]], tags=["public catalog"])
def public_colors(db: Session = Depends(get_db)):
    return ApiResponse(message="Colores obtenidos.", data=CatalogRepository(db).list_reference(ColorModel))


@router.get("/seasons", response_model=ApiResponse[list[SeasonResponse]], tags=["public catalog"])
def public_seasons(db: Session = Depends(get_db)):
    return ApiResponse(message="Temporadas obtenidas.", data=CatalogRepository(db).list_reference(SeasonModel))


@router.get("/collections", response_model=ApiResponse[list[CollectionResponse]], tags=["public catalog"])
def public_collections(db: Session = Depends(get_db)):
    return ApiResponse(message="Colecciones obtenidas.", data=CatalogRepository(db).list_reference(CollectionModel))


@router.get("/admin/products", response_model=ApiResponse[Page[ProductResponse]])
def admin_products(
    actor: CatalogReader, db: Session = Depends(get_db), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    search: str | None = None, category_id: uuid.UUID | None = None, season_id: uuid.UUID | None = None,
    collection_id: uuid.UUID | None = None, size_id: uuid.UUID | None = None, color_id: uuid.UUID | None = None,
    brand: str | None = None, featured: bool | None = None, min_price: Decimal | None = Query(default=None, ge=0),
    max_price: Decimal | None = Query(default=None, ge=0), include_deleted: bool = False,
):
    items, total = CatalogRepository(db).list_products(
        page=page, page_size=page_size, public=False, search=search, category_id=category_id, season_id=season_id,
        collection_id=collection_id, size_id=size_id, color_id=color_id, brand=brand, featured=featured,
        min_price=min_price, max_price=max_price, include_deleted=include_deleted,
    )
    result = Page(items=items, total=total, page=page, page_size=page_size, pages=ceil(total / page_size) if total else 0)
    return ApiResponse(message="Productos obtenidos.", data=result)


@router.post("/admin/products", response_model=ApiResponse[ProductResponse], status_code=status.HTTP_201_CREATED)
def create_product(data: ProductCreate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Producto creado.", data=CatalogService(db).create_product(data, actor))


@router.get("/admin/products/{product_id}", response_model=ApiResponse[ProductResponse])
def admin_product(product_id: uuid.UUID, actor: CatalogReader, db: Session = Depends(get_db)):
    return ApiResponse(message="Producto obtenido.", data=CatalogService(db).require_product(product_id, include_deleted=True))


@router.patch("/admin/products/{product_id}", response_model=ApiResponse[ProductResponse])
def update_product(product_id: uuid.UUID, data: ProductUpdate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Producto actualizado.", data=CatalogService(db).update_product(product_id, data, actor))


@router.post("/admin/products/{product_id}/activate", response_model=ApiResponse[ProductResponse])
def activate_product(product_id: uuid.UUID, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Producto activado.", data=CatalogService(db).set_product_active(product_id, True, actor))


@router.post("/admin/products/{product_id}/deactivate", response_model=ApiResponse[ProductResponse])
def deactivate_product(product_id: uuid.UUID, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Producto desactivado.", data=CatalogService(db).set_product_active(product_id, False, actor))


@router.delete("/admin/products/{product_id}", response_model=ApiResponse[None])
def delete_product(product_id: uuid.UUID, actor: CatalogWriter, db: Session = Depends(get_db)):
    CatalogService(db).delete_product(product_id, actor)
    return ApiResponse(message="Producto eliminado.")


@router.post("/admin/products/{product_id}/variants", response_model=ApiResponse[ProductResponse])
def add_variant(product_id: uuid.UUID, data: VariantCreate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Variante agregada.", data=CatalogService(db).add_variant(product_id, data, actor))


@router.patch("/admin/products/{product_id}/variants/{variant_id}", response_model=ApiResponse[ProductResponse])
def update_variant(product_id: uuid.UUID, variant_id: uuid.UUID, data: VariantUpdate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Variante actualizada.", data=CatalogService(db).update_variant(product_id, variant_id, data, actor))


@router.delete("/admin/products/{product_id}/variants/{variant_id}", response_model=ApiResponse[ProductResponse])
def delete_variant(product_id: uuid.UUID, variant_id: uuid.UUID, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Variante eliminada.", data=CatalogService(db).delete_variant(product_id, variant_id, actor))


@router.post("/admin/products/{product_id}/images", response_model=ApiResponse[ProductResponse])
def add_image(product_id: uuid.UUID, data: ImageCreate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Imagen agregada.", data=CatalogService(db).add_image(product_id, data, actor))


@router.delete("/admin/products/{product_id}/images/{image_id}", response_model=ApiResponse[ProductResponse])
def delete_image(product_id: uuid.UUID, image_id: uuid.UUID, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Imagen eliminada.", data=CatalogService(db).delete_image(product_id, image_id, actor))


@router.post("/admin/products/{product_id}/ar-assets", response_model=ApiResponse[ProductResponse])
def add_ar_asset(product_id: uuid.UUID, data: ARAssetCreate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Activo AR agregado.", data=CatalogService(db).add_ar_asset(product_id, data, actor))


@router.delete("/admin/products/{product_id}/ar-assets/{asset_id}", response_model=ApiResponse[ProductResponse])
def delete_ar_asset(product_id: uuid.UUID, asset_id: uuid.UUID, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Activo AR eliminado.", data=CatalogService(db).delete_ar_asset(product_id, asset_id, actor))


@router.put("/admin/products/{product_id}/suppliers", response_model=ApiResponse[ProductResponse])
def set_product_suppliers(product_id: uuid.UUID, data: SetProductSuppliersRequest, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Proveedores actualizados.", data=CatalogService(db).set_suppliers(product_id, data.suppliers, actor))


@router.get("/admin/categories", response_model=ApiResponse[list[CategoryResponse]])
def admin_categories(actor: CatalogReader, include_inactive: bool = True, db: Session = Depends(get_db)):
    return ApiResponse(message="Categorias obtenidas.", data=CatalogRepository(db).list_reference(CategoryModel, include_inactive))


@router.post("/admin/categories", response_model=ApiResponse[CategoryResponse], status_code=status.HTTP_201_CREATED)
def create_category(data: CategoryCreate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Categoria creada.", data=CatalogService(db).create_category(data, actor))


@router.patch("/admin/categories/{entity_id}", response_model=ApiResponse[CategoryResponse])
def update_category(entity_id: uuid.UUID, data: CategoryUpdate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Categoria actualizada.", data=CatalogService(db).update_category(entity_id, data, actor))


@router.get("/admin/sizes", response_model=ApiResponse[list[SizeResponse]])
def admin_sizes(actor: CatalogReader, include_inactive: bool = True, db: Session = Depends(get_db)):
    return ApiResponse(message="Tallas obtenidas.", data=CatalogRepository(db).list_reference(SizeModel, include_inactive))


@router.post("/admin/sizes", response_model=ApiResponse[SizeResponse], status_code=status.HTTP_201_CREATED)
def create_size(data: SizeCreate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Talla creada.", data=CatalogService(db).create_size(data, actor))


@router.patch("/admin/sizes/{entity_id}", response_model=ApiResponse[SizeResponse])
def update_size(entity_id: uuid.UUID, data: SizeUpdate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Talla actualizada.", data=CatalogService(db).update_size(entity_id, data, actor))


@router.get("/admin/colors", response_model=ApiResponse[list[ColorResponse]])
def admin_colors(actor: CatalogReader, include_inactive: bool = True, db: Session = Depends(get_db)):
    return ApiResponse(message="Colores obtenidos.", data=CatalogRepository(db).list_reference(ColorModel, include_inactive))


@router.post("/admin/colors", response_model=ApiResponse[ColorResponse], status_code=status.HTTP_201_CREATED)
def create_color(data: ColorCreate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Color creado.", data=CatalogService(db).create_color(data, actor))


@router.patch("/admin/colors/{entity_id}", response_model=ApiResponse[ColorResponse])
def update_color(entity_id: uuid.UUID, data: ColorUpdate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Color actualizado.", data=CatalogService(db).update_color(entity_id, data, actor))


@router.get("/admin/seasons", response_model=ApiResponse[list[SeasonResponse]])
def admin_seasons(actor: CatalogReader, include_inactive: bool = True, db: Session = Depends(get_db)):
    return ApiResponse(message="Temporadas obtenidas.", data=CatalogRepository(db).list_reference(SeasonModel, include_inactive))


@router.post("/admin/seasons", response_model=ApiResponse[SeasonResponse], status_code=status.HTTP_201_CREATED)
def create_season(data: SeasonCreate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Temporada creada.", data=CatalogService(db).create_season(data, actor))


@router.patch("/admin/seasons/{entity_id}", response_model=ApiResponse[SeasonResponse])
def update_season(entity_id: uuid.UUID, data: SeasonUpdate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Temporada actualizada.", data=CatalogService(db).update_season(entity_id, data, actor))


@router.get("/admin/collections", response_model=ApiResponse[list[CollectionResponse]])
def admin_collections(actor: CatalogReader, include_inactive: bool = True, db: Session = Depends(get_db)):
    return ApiResponse(message="Colecciones obtenidas.", data=CatalogRepository(db).list_reference(CollectionModel, include_inactive))


@router.post("/admin/collections", response_model=ApiResponse[CollectionResponse], status_code=status.HTTP_201_CREATED)
def create_collection(data: CollectionCreate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Coleccion creada.", data=CatalogService(db).create_collection(data, actor))


@router.patch("/admin/collections/{entity_id}", response_model=ApiResponse[CollectionResponse])
def update_collection(entity_id: uuid.UUID, data: CollectionUpdate, actor: CatalogWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Coleccion actualizada.", data=CatalogService(db).update_collection(entity_id, data, actor))


def _register_reference_state_routes(path: str, model, response_model):
    @router.get(f"/admin/{path}/{{entity_id}}", response_model=ApiResponse[response_model], name=f"get_{path}")
    def get_reference(entity_id: uuid.UUID, actor: CatalogReader, db: Session = Depends(get_db)):
        return ApiResponse(message="Registro obtenido.", data=CatalogService(db).require_reference(model, entity_id))

    @router.post(f"/admin/{path}/{{entity_id}}/activate", response_model=ApiResponse[response_model], name=f"activate_{path}")
    def activate(entity_id: uuid.UUID, actor: CatalogWriter, db: Session = Depends(get_db)):
        return ApiResponse(message="Registro activado.", data=CatalogService(db).set_reference_active(model, entity_id, True, actor))

    @router.post(f"/admin/{path}/{{entity_id}}/deactivate", response_model=ApiResponse[response_model], name=f"deactivate_{path}")
    def deactivate(entity_id: uuid.UUID, actor: CatalogWriter, db: Session = Depends(get_db)):
        return ApiResponse(message="Registro desactivado.", data=CatalogService(db).set_reference_active(model, entity_id, False, actor))

    @router.delete(f"/admin/{path}/{{entity_id}}", response_model=ApiResponse[None], name=f"delete_{path}")
    def delete(entity_id: uuid.UUID, actor: CatalogWriter, db: Session = Depends(get_db)):
        CatalogService(db).delete_reference(model, entity_id, actor)
        return ApiResponse(message="Registro eliminado.")


_register_reference_state_routes("categories", CategoryModel, CategoryResponse)
_register_reference_state_routes("sizes", SizeModel, SizeResponse)
_register_reference_state_routes("colors", ColorModel, ColorResponse)
_register_reference_state_routes("seasons", SeasonModel, SeasonResponse)
_register_reference_state_routes("collections", CollectionModel, CollectionResponse)
