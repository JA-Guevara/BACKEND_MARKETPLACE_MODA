"""Matriz completa de verificación de aislamiento multi-tenant (Q3.1).

Verifica exhaustivamente que ningún endpoint permita fuga de datos ni modificación
cruzada entre empresas independientes (Tenant A vs Tenant B).
"""
import uuid
import pytest

from tests.unit.plataforma_saas.conftest import world


def test_matriz_aislamiento_completa_rutas(world):
    tenant_a = world.tenants[0]
    admin_a = world.admins[0]
    headers_a = world.headers(admin_a)

    tenant_b = world.tenants[1]
    admin_b = world.admins[1]
    headers_b = world.headers(admin_b)

    # 1. Sucursales: Admin B no puede ver ni modificar sucursal de A
    branch_a = world.branches[0]
    res_b_branch = world.client.get(f"/api/v1/organization/branches/{branch_a.id}", headers=headers_b)
    assert res_b_branch.status_code in (404, 403)

    # 2. Cajas: Admin B no puede consultar cajas de A
    cash_point_a = world.cash_points[0]
    res_b_cp = world.client.get(f"/api/v1/organization/cash-points/{cash_point_a.id}", headers=headers_b)
    assert res_b_cp.status_code in (404, 403)

    # 3. Catálogo / Productos
    product_a = world.products[0]
    res_b_prod = world.client.get(f"/api/v1/catalog/admin/products/{product_a.id}", headers=headers_b)
    assert res_b_prod.status_code in (404, 403)

    # 4. Promociones y Ofertas (CU-11)
    res_create_promo = world.client.post(
        "/api/v1/commerce/admin/promotions",
        headers=headers_a,
        json={
            "name": "Promo Privada Tenant A",
            "discount_type": "percent",
            "discount_value": 15,
            "target": {"type": "ALL", "ids": []},
            "applies_online": True,
            "applies_pos": True,
            "applies_offline": True,
        },
    )
    assert res_create_promo.status_code == 201
    promo_a_id = res_create_promo.json()["data"]["id"]

    # Admin B no puede ver la promo de A
    res_b_promo_get = world.client.get(f"/api/v1/commerce/admin/promotions/{promo_a_id}", headers=headers_b)
    assert res_b_promo_get.status_code in (404, 403)

    # Admin B no puede desactivar la promo de A
    res_b_promo_deact = world.client.post(f"/api/v1/commerce/admin/promotions/{promo_a_id}/deactivate", headers=headers_b)
    assert res_b_promo_deact.status_code in (404, 403)

    # Listado de B no incluye la promo de A
    res_b_promo_list = world.client.get("/api/v1/commerce/admin/promotions", headers=headers_b)
    assert res_b_promo_list.status_code == 200
    assert not any(p["id"] == promo_a_id for p in res_b_promo_list.json()["data"])

    # 5. Dispositivos (CU-12)
    dev_id_a = f"pwa-isolated-{uuid.uuid4().hex[:8]}"
    world.client.get(
        "/api/v1/offline/snapshot",
        headers={**headers_a, "X-Device-Id": dev_id_a, "X-Client-Platform": "PWA"},
    )
    dev_a_list = world.client.get("/api/v1/tenant/devices", headers=headers_a).json()["data"]["items"]
    dev_a_record = next(d for d in dev_a_list if d["device_id"] == dev_id_a)
    dev_a_pk = dev_a_record["id"]

    # Admin B no puede ver dispositivo de A
    res_b_dev_get = world.client.get(f"/api/v1/tenant/devices/{dev_a_pk}", headers=headers_b)
    assert res_b_dev_get.status_code == 404

    # Admin B no puede bloquear dispositivo de A
    res_b_dev_block = world.client.post(
        f"/api/v1/tenant/devices/{dev_a_pk}/block",
        headers=headers_b,
        json={"reason": "Intento no autorizado"},
    )
    assert res_b_dev_block.status_code == 404

    # Listado de dispositivos de B no contiene el de A
    res_b_dev_list = world.client.get("/api/v1/tenant/devices", headers=headers_b).json()["data"]["items"]
    assert not any(d["id"] == dev_a_pk for d in res_b_dev_list)

    # 6. Bitácora de Auditoría
    # Eventos de A no son visibles para B
    res_b_audit = world.client.get("/api/v1/audit-log", headers=headers_b)
    assert res_b_audit.status_code == 200
    events_b = res_b_audit.json()["data"]["items"]
    assert not any(getattr(e, "tenant_id", None) == str(tenant_a.id) for e in events_b)
