import json
import uuid
from decimal import Decimal
from math import ceil
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.config.settings import settings
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.shared.exceptions.domain_exception import NotFoundError
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page
from src.usuarios_catalogo.application.services.catalog_service import CatalogService
from src.usuarios_catalogo.infrastructure.models.catalog import CategoryModel, CollectionModel, ColorModel, ProductModel, SeasonModel, SizeModel
from src.usuarios_catalogo.infrastructure.repositories.catalog_repository import CatalogRepository
from src.usuarios_catalogo.web.schemas.catalog import ARAssetCreate, CategoryCreate, CategoryResponse, CategoryUpdate, CollectionCreate, CollectionResponse, CollectionUpdate, ColorCreate, ColorResponse, ColorUpdate, ImageCreate, ProductCreate, ProductDraftRequest, ProductResponse, ProductUpdate, PublicProductResponse, SeasonCreate, SeasonResponse, SeasonUpdate, SetProductSuppliersRequest, SizeCreate, SizeResponse, SizeUpdate, VariantCreate, VariantUpdate


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


PRODUCT_DRAFT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "base_price": {"type": "number"},
        "category_name": {"type": "string"},
        "brand": {"type": "string"},
        "gender": {"type": "string"},
        "description": {"type": "string"},
    },
    "required": ["name", "base_price", "category_name", "brand", "gender", "description"],
}


def _normalize_name(text: str) -> str:
    accents = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}
    return "".join(accents.get(ch, ch) for ch in text.lower()).strip()


def _draft_unavailable(message: str) -> ApiResponse:
    return ApiResponse(message=message, data={
        "available": False, "name": "", "base_price": 0.0, "category_id": None,
        "category_name": "", "brand": None, "gender": None, "description": "", "matched": False,
    })


@router.post("/admin/products/draft", tags=["catalog"])
def draft_product(data: ProductDraftRequest, actor: CatalogWriter, db: Session = Depends(get_db)):
    """Extrae, con IA, los campos de una prenda nueva a partir de un pedido en
    lenguaje natural (ej.: "registrame una campera de cuero a 450 bolivianos").
    NO crea nada: el admin revisa el borrador y confirma con POST /admin/products
    como cualquier alta manual. category_name solo se acepta si coincide EXACTO
    (normalizado) con una categoria activa real; nunca se inventa un id."""
    if not settings.ai_api_key:
        return _draft_unavailable("El asistente de IA no esta configurado todavia.")
    categories = [{"id": str(c.id), "name": c.name} for c in db.scalars(select(CategoryModel).where(CategoryModel.is_active.is_(True)))]
    system = (
        "Extraes los datos de una prenda nueva a partir de un pedido en espanol, para el panel de "
        "administracion de FashionStore. Devolves SOLO los campos del esquema, sin texto extra.\n"
        "category_name: el nombre EXACTO de una de estas categorias si hay coincidencia clara, o cadena "
        "vacia si no hay ninguna coincidencia razonable: " + ", ".join(c["name"] for c in categories) + ".\n"
        "base_price: el precio numerico que mencionen (sin simbolo de moneda); 0 si no dan un precio claro.\n"
        "description: una oracion breve y honesta describiendo la prenda; si no hay info suficiente, "
        "repeti el nombre a modo de descripcion minima."
    )
    try:
        result = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": "Bearer " + settings.ai_api_key},
            json={
                "model": settings.ai_model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": data.message}],
                "max_tokens": 300,
                "response_format": {"type": "json_schema", "json_schema": {"name": "product_draft", "strict": True, "schema": PRODUCT_DRAFT_SCHEMA}},
            },
            timeout=25,
        )
        result.raise_for_status()
        parsed = json.loads(result.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        return _draft_unavailable("No pude interpretar el pedido en este momento. Intenta de nuevo.")

    wanted = _normalize_name(str(parsed.get("category_name") or ""))
    matched = next((c for c in categories if _normalize_name(c["name"]) == wanted), None) if wanted else None
    try:
        price = max(0.0, float(parsed.get("base_price") or 0))
    except (TypeError, ValueError):
        price = 0.0

    return ApiResponse(message="Borrador generado.", data={
        "available": True,
        "name": str(parsed.get("name") or "").strip()[:180],
        "base_price": price,
        "category_id": matched["id"] if matched else None,
        "category_name": matched["name"] if matched else "",
        "brand": (str(parsed.get("brand") or "").strip()[:100] or None),
        "gender": (str(parsed.get("gender") or "").strip()[:30] or None),
        "description": str(parsed.get("description") or "").strip()[:2000],
        "matched": matched is not None,
    })


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
