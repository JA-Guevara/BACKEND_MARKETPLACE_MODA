"""Pruebas unitarias HTTP para cuotas, avisos, onboarding, solicitudes y plantillas (RS-3)."""
import pytest
from uuid import UUID
from sqlalchemy import func, select

from src.inventario_sucursales.infrastructure.models.organization import BranchModel, CashPointModel
from src.plataforma_saas.application.catalog_template_service import CatalogTemplateService
from src.plataforma_saas.application.tenant_service import TenantService
from src.plataforma_saas.application.usage_service import UsageService
from src.plataforma_saas.infrastructure.models.storefront import (
    CatalogTemplateModel,
    UpgradeRequestModel,
    UsageAlertModel,
)
from src.plataforma_saas.web.schemas.storefront import CatalogTemplateIn, UpgradeRequestIn
from src.plataforma_saas.web.schemas.tenants import TenantAdminInput, TenantCreate
from src.usuarios_catalogo.infrastructure.models.catalog import CategoryModel
from tests.unit.plataforma_saas.conftest import make_token


def test_usage_and_quota_alert_at_100_percent(client, world):
    # Tenant A tiene plan BASICO (límite 2 sucursales). Ya tiene 1 sucursal ("Central").
    token_admin_a = make_token(world.admins[0])

    # Crear 2.ª sucursal
    branch_2 = BranchModel(
        tenant_id=world.tenant_a.id,
        name="Sucursal 2",
        code="SUC-02",
        address="Av. Banzer",
        city_id=world.branches[0].city_id,
        is_active=True,
    )
    world.db.add(branch_2)
    world.db.commit()

    # Ejecutar aviso
    usage_svc = UsageService(world.db)
    usage_svc.avisar_si_corresponde(world.tenant_a.id, "branches")

    # Verificar que existe 1 alerta de nivel 100
    alerts = world.db.scalars(
        select(UsageAlertModel).where(
            UsageAlertModel.tenant_id == world.tenant_a.id,
            UsageAlertModel.limit_code == "branches",
            UsageAlertModel.level == 100,
        )
    ).all()
    assert len(alerts) == 1

    # Repetir no duplica
    usage_svc.avisar_si_corresponde(world.tenant_a.id, "branches")
    alerts_2 = world.db.scalars(
        select(UsageAlertModel).where(
            UsageAlertModel.tenant_id == world.tenant_a.id,
            UsageAlertModel.limit_code == "branches",
            UsageAlertModel.level == 100,
        )
    ).all()
    assert len(alerts_2) == 1


def test_import_template_twice_does_not_duplicate_categories(client, world):
    tpl_svc = CatalogTemplateService(world.db)
    tpl_data = CatalogTemplateIn(
        code="boutique-test",
        name="Boutique Test",
        payload={
            "categories": ["Vestidos de Gala", "Blusas Exclusivas"],
            "sizes": ["S", "M"],
            "colors": ["Negro", "Marfil"],
            "seasons": ["Invierno 2026"],
        },
    )
    tpl_svc.crear(tpl_data, world.platform_user)

    # 1.ª importación
    res1 = tpl_svc.importar(world.tenant_a.id, "boutique-test", world.admins[0])
    assert res1.imported_counts["categories"] == 2

    # 2.ª importación
    res2 = tpl_svc.importar(world.tenant_a.id, "boutique-test", world.admins[0])
    assert res2.imported_counts["categories"] == 0

    # Total de categorías en base de datos con ese nombre es exactamente 1 de cada una
    count_gala = world.db.scalar(
        select(func.count(CategoryModel.id)).where(
            CategoryModel.tenant_id == world.tenant_a.id,
            CategoryModel.name == "Vestidos de Gala",
        )
    )
    assert count_gala == 1


def test_changing_template_does_not_modify_already_imported_tenant(client, world):
    tpl_svc = CatalogTemplateService(world.db)
    tpl_data = CatalogTemplateIn(
        code="urbana-test",
        name="Urbana Test",
        payload={
            "categories": ["Hoodies Streetwear"],
            "sizes": ["L"],
            "colors": ["Negro"],
            "seasons": ["Atemporal"],
        },
    )
    tpl = tpl_svc.crear(tpl_data, world.platform_user)
    tpl_svc.importar(world.tenant_a.id, "urbana-test", world.admins[0])

    # Modificar la plantilla
    tpl_svc.actualizar(
        tpl.id,
        CatalogTemplateIn(
            code="urbana-test",
            name="Urbana Renombrada",
            payload={"categories": ["Pantalones Baggy"]},
        ),
        world.platform_user,
    )

    # La empresa A conserva "Hoodies Streetwear" y NO tiene "Pantalones Baggy"
    has_hoodies = world.db.scalar(
        select(CategoryModel).where(
            CategoryModel.tenant_id == world.tenant_a.id,
            CategoryModel.name == "Hoodies Streetwear",
        )
    )
    assert has_hoodies is not None

    has_baggy = world.db.scalar(
        select(CategoryModel).where(
            CategoryModel.tenant_id == world.tenant_a.id,
            CategoryModel.name == "Pantalones Baggy",
        )
    )
    assert has_baggy is None


def test_upgrade_request_duplicate_open_returns_409(client, world):
    token_admin_a = make_token(world.admins[0])

    # 1.ª solicitud ABIERTA
    resp1 = client.post(
        "/api/v1/tenant/upgrade-requests",
        json={"kind": "LIMIT", "target": "branches", "message": "Necesitamos 2 sucursales más"},
        headers={"Authorization": f"Bearer {token_admin_a}"},
    )
    assert resp1.status_code == 200

    # 2.ª solicitud del mismo tipo mientras está ABIERTA -> 409
    resp2 = client.post(
        "/api/v1/tenant/upgrade-requests",
        json={"kind": "LIMIT", "target": "branches", "message": "Otra solicitud"},
        headers={"Authorization": f"Bearer {token_admin_a}"},
    )
    assert resp2.status_code == 409
    assert "upgrade_request_open" in resp2.text


def test_handle_upgrade_request_by_platform_sets_atendida(client, world):
    token_admin_a = make_token(world.admins[0])
    token_platform = make_token(world.platform_user)

    # Crear solicitud
    resp1 = client.post(
        "/api/v1/tenant/upgrade-requests",
        json={"kind": "PLAN", "target": "PROFESIONAL", "message": "Queremos subir a profesional"},
        headers={"Authorization": f"Bearer {token_admin_a}"},
    )
    req_id = resp1.json()["data"]["id"]

    # Plataforma atiende la solicitud
    resp_handle = client.post(
        f"/api/v1/platform/upgrade-requests/{req_id}/handle",
        json={"response": "Plan profesional habilitado por 30 días de cortesía."},
        headers={"Authorization": f"Bearer {token_platform}"},
    )
    assert resp_handle.status_code == 200
    assert resp_handle.json()["data"]["status"] == "ATENDIDA"

    # Verificar en base de datos
    req = world.db.get(UpgradeRequestModel, UUID(str(req_id)))
    assert req.status == "ATENDIDA"
    assert req.response == "Plan profesional habilitado por 30 días de cortesía."


def test_create_tenant_with_template_code_imports_dictionaries_and_unpublished(client, world):
    # Sembrar plantilla
    tpl_svc = CatalogTemplateService(world.db)
    tpl_svc.crear(
        CatalogTemplateIn(
            code="deportiva-seed",
            name="Deportiva Seed",
            payload={
                "categories": ["Tops Fitness", "Leggings Gym"],
                "sizes": ["S", "M"],
                "colors": ["Negro"],
                "seasons": ["Continuo"],
            },
        ),
        world.platform_user,
    )

    token_platform = make_token(world.platform_user)
    tenant_payload = {
        "legal_name": "Empresa Deportiva SRL",
        "trade_name": "Sport Moda",
        "tax_id": "7788990011",
        "slug": "sport-moda",
        "contact_email": "info@sportmoda.bo",
        "phone": "+591 76543210",
        "admin": {
            "first_name": "Carlos",
            "last_name": "Sport",
            "email": "carlos@sportmoda.bo",
        },
        "plan_code": "BASICO",
        "template_code": "deportiva-seed",
    }

    resp = client.post(
        "/api/v1/platform/tenants",
        json=tenant_payload,
        headers={"Authorization": f"Bearer {token_platform}"},
    )
    assert resp.status_code == 201
    tenant_data = resp.json()["data"]
    tenant_id = UUID(str(tenant_data["id"]))

    # Nace con is_published = False
    assert tenant_data["is_published"] is False

    # Categorías de la plantilla fueron copiadas
    cats = world.db.scalars(
        select(CategoryModel).where(CategoryModel.tenant_id == tenant_id)
    ).all()
    cat_names = [c.name for c in cats]
    assert "Tops Fitness" in cat_names
    assert "Leggings Gym" in cat_names
