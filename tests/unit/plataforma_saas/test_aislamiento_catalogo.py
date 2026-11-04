import uuid
from sqlalchemy import select
from src.usuarios_catalogo.infrastructure.models.catalog import CategoryModel, ColorModel, SeasonModel, SizeModel
from src.plataforma_saas.application.tenant_service import TenantService
from src.plataforma_saas.web.schemas.tenants import TenantCreate, TenantAdminInput


def test_admin_a_solo_ve_sus_categorias(world):
    resp = world.client.get("/api/v1/catalog/admin/categories", headers=world.headers(world.admins[0]))
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Solo debe ver las de su tenant (A)
    assert len(data) >= 1
    names = [c["name"] for c in data]
    assert "Vestidos" in names
    assert "Vestidos B" not in names


def test_admin_a_patch_talla_de_b_retorna_404(world):
    size_b = world.db.scalar(select(SizeModel).where(SizeModel.tenant_id == world.tenants[1].id))
    assert size_b is not None
    resp = world.client.patch(
        f"/api/v1/catalog/admin/sizes/{size_b.id}",
        json={"name": "Modificada por A"},
        headers=world.headers(world.admins[0]),
    )
    assert resp.status_code == 404


def test_admin_a_post_producto_con_categoria_de_b_retorna_404(world):
    cat_b = world.db.scalar(select(CategoryModel).where(CategoryModel.tenant_id == world.tenants[1].id))
    assert cat_b is not None
    payload = {
        "name": "Producto Hacker",
        "description": "Intenta cruzar categoria",
        "base_price": 200,
        "category_id": str(cat_b.id),
        "variants": [
            {
                "size_id": str(world.size.id),
                "color_id": str(world.color.id),
                "sku": "HACK-01",
            }
        ],
        "images": [],
        "suppliers": [],
    }
    resp = world.client.post(
        "/api/v1/catalog/admin/products",
        json=payload,
        headers=world.headers(world.admins[0]),
    )
    assert resp.status_code == 404


def test_get_public_categories_con_slug_de_b_retorna_solo_de_b(world):
    resp = world.client.get(
        "/api/v1/catalog/categories",
        headers={"X-Tenant-Slug": world.tenants[1].slug},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    names = [c["name"] for c in data]
    assert "Vestidos B" in names
    assert "Vestidos" not in names


def test_admin_a_puede_crear_categoria_con_nombre_existente_en_b(world):
    # En B ya existe 'Vestidos B', vamos a crear 'Vestidos B' en A
    resp = world.client.post(
        "/api/v1/catalog/admin/categories",
        json={"name": "Vestidos B"},
        headers=world.headers(world.admins[0]),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["name"] == "Vestidos B"


def test_admin_a_post_cities_retorna_403_y_super_admin_retorna_201(world):
    payload = {"name": "Cochabamba", "department": "Cochabamba", "country": "Bolivia"}
    # Admin A intenta crear ciudad -> 403
    resp_admin = world.client.post(
        "/api/v1/organization/cities",
        json=payload,
        headers=world.headers(world.admins[0]),
    )
    assert resp_admin.status_code == 403

    # Super admin (plataforma) crea ciudad -> 201
    resp_platform = world.client.post(
        "/api/v1/organization/cities",
        json=payload,
        headers=world.headers(world.platform),
    )
    assert resp_platform.status_code == 201
    assert resp_platform.json()["data"]["name"] == "Cochabamba"


def test_tenant_service_registrar_siembra_catalogo(world):
    service = TenantService(world.db, world.platform)
    create_dto = TenantCreate(
        legal_name="Nueva Empresa S.A.",
        trade_name="Nueva Moda",
        tax_id="999888777",
        slug="nueva-moda",
        contact_email="admin@nuevamoda.com",
        plan_code="BASICO",
        admin=TenantAdminInput(
            email="admin@nuevamoda.com",
            first_name="Admin",
            last_name="Nuevo",
        ),
    )
    tenant = service.registrar(create_dto)
    world.db.flush()

    sizes = world.db.scalars(select(SizeModel).where(SizeModel.tenant_id == tenant.id)).all()
    colors = world.db.scalars(select(ColorModel).where(ColorModel.tenant_id == tenant.id)).all()
    categories = world.db.scalars(select(CategoryModel).where(CategoryModel.tenant_id == tenant.id)).all()
    seasons = world.db.scalars(select(SeasonModel).where(SeasonModel.tenant_id == tenant.id)).all()

    assert len(sizes) == 5
    assert len(colors) == 5
    assert len(categories) == 4
    assert len(seasons) == 1
