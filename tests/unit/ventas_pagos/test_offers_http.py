"""Pruebas HTTP para gestión de ofertas y aislamiento (CU-11)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

import pytest

from tests.unit.plataforma_saas.conftest import world


def test_gestion_ofertas_flujo_completo(world):
    tenant_a = world.tenants[0]
    admin_a = world.admins[0]
    headers_a = world.headers(admin_a)
    cat = world.category

    # 1. Vista previa de oferta (POST /commerce/admin/promotions/preview)
    preview_res = world.client.post(
        "/api/v1/commerce/admin/promotions/preview",
        headers=headers_a,
        json={
            "name": "20% en Vestidos",
            "discount_type": "percent",
            "discount_value": 20,
            "target": {"type": "CATEGORY", "ids": [str(cat.id)]},
            "applies_online": True,
            "applies_pos": True,
            "applies_offline": True,
        },
    )
    assert preview_res.status_code == 200, preview_res.text
    preview_data = preview_res.json()["data"]
    assert len(preview_data["items"]) >= 1
    assert float(preview_data["items"][0]["final"]) == 120.0  # 150 base * 0.8
    assert len(preview_data["errors"]) == 0

    # 2. Crear oferta (POST /commerce/admin/promotions)
    create_res = world.client.post(
        "/api/v1/commerce/admin/promotions",
        headers=headers_a,
        json={
            "name": "20% en Vestidos",
            "code": "VESTIDOS20",
            "description": "Descuento especial de temporada",
            "discount_type": "percent",
            "discount_value": 20,
            "target": {"type": "CATEGORY", "ids": [str(cat.id)]},
            "applies_online": True,
            "applies_pos": True,
            "applies_offline": False,
        },
    )
    assert create_res.status_code == 201, create_res.text
    promo_id = create_res.json()["data"]["id"]

    # 3. Listar ofertas (GET /commerce/admin/promotions)
    list_res = world.client.get("/api/v1/commerce/admin/promotions", headers=headers_a)
    assert list_res.status_code == 200
    promos = list_res.json()["data"]
    assert any(p["id"] == promo_id and p["status"] == "ACTIVA" for p in promos)

    # 4. Desactivar oferta (3b: POST .../deactivate)
    deact_res = world.client.post(f"/api/v1/commerce/admin/promotions/{promo_id}/deactivate", headers=headers_a)
    assert deact_res.status_code == 200
    assert deact_res.json()["data"]["status"] == "INACTIVA"
    assert deact_res.json()["data"]["is_active"] is False

    # 5. Reactivar oferta
    act_res = world.client.post(f"/api/v1/commerce/admin/promotions/{promo_id}/activate", headers=headers_a)
    assert act_res.status_code == 200
    assert act_res.json()["data"]["status"] == "ACTIVA"
    assert act_res.json()["data"]["is_active"] is True


def test_aislamiento_entre_empresas(world):
    admin_a = world.admins[0]
    admin_b = world.admins[1]
    headers_a = world.headers(admin_a)
    headers_b = world.headers(admin_b)

    # Crear oferta en Tenant A
    create_res = world.client.post(
        "/api/v1/commerce/admin/promotions",
        headers=headers_a,
        json={
            "name": "Promo Secreta Empresa A",
            "code": "SECRETA",
            "discount_type": "percent",
            "discount_value": 15,
            "target": {"type": "ALL", "ids": []},
        },
    )
    assert create_res.status_code == 201
    promo_a_id = create_res.json()["data"]["id"]

    # Tenant B intenta listar promociones: no debe ver la promo de Empresa A
    list_b = world.client.get("/api/v1/commerce/admin/promotions", headers=headers_b)
    assert list_b.status_code == 200
    promos_b = list_b.json()["data"]
    assert not any(p["id"] == promo_a_id for p in promos_b)

    # Tenant B intenta desactivar promo de Empresa A -> 404
    deact_b = world.client.post(f"/api/v1/commerce/admin/promotions/{promo_a_id}/deactivate", headers=headers_b)
    assert deact_b.status_code == 404

    # Tenant B PUEDE crear una promo con el mismo código de cupón 'SECRETA' en su propia empresa
    create_b = world.client.post(
        "/api/v1/commerce/admin/promotions",
        headers=headers_b,
        json={
            "name": "Promo Empresa B con mismo código",
            "code": "SECRETA",
            "discount_type": "percent",
            "discount_value": 10,
            "target": {"type": "ALL", "ids": []},
        },
    )
    assert create_b.status_code == 201
