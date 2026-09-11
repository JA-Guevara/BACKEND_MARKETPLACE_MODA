"""Explicit spreadsheet allow-list. Never expose arbitrary models or security fields."""
from dataclasses import dataclass, field

from src.usuarios_catalogo.infrastructure.models import catalog as cm
from src.usuarios_catalogo.web.schemas import catalog as cs
from src.inventario_sucursales.infrastructure.models import organization as om
from src.inventario_sucursales.web.schemas import organization as os
from src.usuarios_catalogo.application.services.catalog_service import CatalogService
from src.inventario_sucursales.application.services.organization_service import OrganizationService


@dataclass(frozen=True)
class Reference:
    model: type
    keys: tuple[str, ...]
    target: str


@dataclass(frozen=True)
class Resource:
    model: type
    schema: type
    update_schema: type
    service: type
    singular: str
    permission: str
    keys: tuple[str, ...]
    columns: tuple[str, ...]
    references: dict[str, Reference] = field(default_factory=dict)


season = Reference(cm.SeasonModel, ('name',), 'season_id')
category = Reference(cm.CategoryModel, ('slug',), 'category_id')
collection = Reference(cm.CollectionModel, ('name', 'season_id'), 'collection_id')
city = Reference(om.CityModel, ('name', 'department', 'country'), 'city_id')
branch = Reference(om.BranchModel, ('code',), 'branch_id')


def catalog(model, schema, update, singular, keys, columns, references=None):
    return Resource(model, schema, update, CatalogService, singular, 'catalog', keys, columns, references or {})


def organization(model, schema, update, singular, keys, columns, references=None):
    return Resource(model, schema, update, OrganizationService, singular,
                    'suppliers' if singular == 'supplier' else 'branches', keys, columns, references or {})


RESOURCES = {
    'categories': catalog(cm.CategoryModel, cs.CategoryCreate, cs.CategoryUpdate, 'category', ('slug',),
                          ('slug', 'name', 'description', 'parent_slug'),
                          {'parent_slug': Reference(cm.CategoryModel, ('slug',), 'parent_id')}),
    'sizes': catalog(cm.SizeModel, cs.SizeCreate, cs.SizeUpdate, 'size', ('code',), ('code', 'name', 'sort_order')),
    'colors': catalog(cm.ColorModel, cs.ColorCreate, cs.ColorUpdate, 'color', ('name',), ('name', 'hex_code')),
    'seasons': catalog(cm.SeasonModel, cs.SeasonCreate, cs.SeasonUpdate, 'season', ('name',),
                       ('name', 'description', 'start_date', 'end_date')),
    'collections': catalog(cm.CollectionModel, cs.CollectionCreate, cs.CollectionUpdate, 'collection', ('name', 'season_id'),
                           ('name', 'description', 'season_name'), {'season_name': season}),
    'products': catalog(cm.ProductModel, cs.ProductCreate, cs.ProductUpdate, 'product', ('slug',),
                        ('slug', 'name', 'description', 'brand', 'gender', 'base_price', 'category_slug',
                         'season_name', 'collection_key', 'is_featured'),
                        {'category_slug': category, 'season_name': season, 'collection_key': collection}),
    'variants': catalog(cm.ProductVariantModel, cs.VariantCreate, cs.VariantUpdate, 'variant', ('sku',),
                        ('sku', 'product_slug', 'size_code', 'color_name', 'barcode', 'price_override'),
                        {'product_slug': Reference(cm.ProductModel, ('slug',), 'product_id'),
                         'size_code': Reference(cm.SizeModel, ('code',), 'size_id'),
                         'color_name': Reference(cm.ColorModel, ('name',), 'color_id')}),
    'suppliers': organization(om.SupplierModel, os.SupplierCreate, os.SupplierUpdate, 'supplier', ('tax_id',),
                              ('tax_id', 'business_name', 'trade_name', 'contact_name', 'email', 'phone', 'address', 'city', 'notes')),
    'cities': organization(om.CityModel, os.CityCreate, os.CityUpdate, 'city', ('name', 'department', 'country'),
                           ('name', 'department', 'country')),
    'branches': organization(om.BranchModel, os.BranchCreate, os.BranchUpdate, 'branch', ('code',),
                             ('code', 'name', 'city_key', 'address', 'phone', 'latitude', 'longitude'), {'city_key': city}),
    'cash-points': organization(om.CashPointModel, os.CashPointCreate, os.CashPointUpdate, 'cash_point', ('branch_id', 'code'),
                                ('branch_code', 'code', 'name'), {'branch_code': branch}),
}
