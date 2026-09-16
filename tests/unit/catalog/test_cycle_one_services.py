from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.base import Base
from src.inventario_sucursales.application.services.organization_service import OrganizationService
from src.inventario_sucursales.web.schemas.organization import BranchCreate, CashPointCreate, CityCreate, SupplierCreate
from src.usuarios_catalogo.application.services.catalog_service import CatalogService
from src.usuarios_catalogo.web.schemas.catalog import CategoryCreate, ColorCreate, ImageCreate, ProductCreate, ProductSupplierInput, SizeCreate, VariantCreate


def make_session() -> tuple[Session, UserModel]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    actor = UserModel(
        email="admin@fashionstore.test",
        password_hash="not-used-in-this-test",
        first_name="Admin",
        last_name="FashionStore",
        is_active=True,
        is_verified=True,
    )
    session.add(actor)
    session.commit()
    return session, actor


def test_cycle_one_organization_and_catalog_flow() -> None:
    db, actor = make_session()
    organization = OrganizationService(db)
    city = organization.create_city(CityCreate(name="Santa Cruz", department="Santa Cruz"), actor)
    branch = organization.create_branch(
        BranchCreate(code="SCZ-01", name="Sucursal Central", city_id=city.id, address="Av. Principal 123"),
        actor,
    )
    cash_point = organization.create_cash_point(
        CashPointCreate(branch_id=branch.id, code="CAJA-01", name="Caja principal"), actor
    )
    supplier = organization.create_supplier(
        SupplierCreate(business_name="Textiles del Oriente", tax_id="NIT-123"), actor
    )

    catalog = CatalogService(db)
    category = catalog.create_category(CategoryCreate(name="Vestidos"), actor)
    size = catalog.create_size(SizeCreate(code="M", name="Mediana", sort_order=20), actor)
    color = catalog.create_color(ColorCreate(name="Rojo", hex_code="#FF0000"), actor)
    product = catalog.create_product(
        ProductCreate(
            name="Vestido primavera",
            description="Vestido ligero para temporada de primavera.",
            brand="FashionStore",
            gender="mujer",
            base_price=Decimal("249.90"),
            category_id=category.id,
            variants=[VariantCreate(size_id=size.id, color_id=color.id, sku="VES-PRI-M-ROJ")],
            images=[ImageCreate(url="https://cdn.example.com/vestido.jpg", is_primary=True)],
            suppliers=[ProductSupplierInput(supplier_id=supplier.id, unit_cost=Decimal("120.00"), is_primary=True)],
        ),
        actor,
    )

    public_page = catalog.public_page(page=1, page_size=24, include_deleted=False)
    assert city.id == branch.city_id
    assert cash_point.branch_id == branch.id
    assert product.slug == "vestido-primavera"
    assert public_page.total == 1
    assert public_page.items[0].variants[0].sku == "VES-PRI-M-ROJ"
    assert not hasattr(public_page.items[0], "suppliers")


def test_soft_deleted_product_is_hidden_from_public_catalog() -> None:
    db, actor = make_session()
    catalog = CatalogService(db)
    category = catalog.create_category(CategoryCreate(name="Camisas"), actor)
    product = catalog.create_product(
        ProductCreate(
            name="Camisa clasica",
            description="Camisa clasica de prueba para el catalogo.",
            base_price=Decimal("99.90"),
            category_id=category.id,
        ),
        actor,
    )

    catalog.delete_product(product.id, actor)

    public_page = catalog.public_page(page=1, page_size=24, include_deleted=False)
    assert public_page.total == 0
    assert catalog.require_product(product.id, include_deleted=True).deleted_at is not None


def test_ar_asset_update_activa_recurso_por_default_y_corrige_url() -> None:
    """Etapa 5: edicion de recursos AR. Al activar uno, los demas del mismo tipo
    quedan inactivos (el probador sabe cual usar) y se pueden corregir las URLs."""
    from src.usuarios_catalogo.web.schemas.catalog import ARAssetCreate, ARAssetUpdate

    db, actor = make_session()
    catalog = CatalogService(db)
    category = catalog.create_category(CategoryCreate(name="Camperas"), actor)
    product = catalog.create_product(
        ProductCreate(name="Campera de cuero", description="Campera para probador.",
                      base_price=Decimal("450.00"), category_id=category.id),
        actor,
    )
    catalog.add_ar_asset(product.id, ARAssetCreate(asset_type="image_overlay",
                                                   asset_url="https://cdn.example.com/overlay_v1.png"), actor)
    catalog.add_ar_asset(product.id, ARAssetCreate(asset_type="image_overlay",
                                                   asset_url="https://cdn.example.com/overlay_v2.png"), actor)

    # Refrescar la colección de recursos (en sesiones nuevas se carga sola;
    # acá el identity map mantiene la colección vieja de create_product).
    db.expire_all()
    second = catalog.require_product(product.id)

    assets = second.ar_assets
    assert len(assets) == 2
    first_id, second_id = assets[0].id, assets[1].id

    updated = catalog.update_ar_asset(
        product.id, second_id,
        ARAssetUpdate(is_active=True, asset_url="https://cdn.example.com/overlay_v2_final.png"),
        actor,
    )
    by_id = {a.id: a for a in updated.ar_assets}
    assert by_id[second_id].is_active is True
    assert by_id[second_id].asset_url == "https://cdn.example.com/overlay_v2_final.png"
    assert by_id[first_id].is_active is False

    # Desactivar el activo por defecto también funciona (edición campo a campo).
    deactivated = catalog.update_ar_asset(product.id, second_id, ARAssetUpdate(is_active=False), actor)
    assert {a.id: a.is_active for a in deactivated.ar_assets}[second_id] is False
