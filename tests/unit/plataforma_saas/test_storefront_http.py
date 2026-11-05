"""Pruebas de aislamiento HTTP y contratos para tienda pública y marca (RS-3)."""
import pytest
from uuid import uuid4

from src.plataforma_saas.infrastructure.models.storefront import TenantPaymentMethodModel
from src.usuarios_catalogo.infrastructure.models.catalog import ProductImageModel
from src.ventas_pagos.infrastructure.models import OrderModel
from tests.unit.plataforma_saas.conftest import make_token


def test_public_catalog_reads_priority_to_slug_even_with_other_tenant_token(client, world):
    # Cliente de Empresa A visita el catálogo de Empresa B vía X-Tenant-Slug
    token_client_a = make_token(world.customers[0])

    world.tenant_b.is_published = True
    world.db.commit()

    resp = client.get(
        "/api/v1/catalog/products",
        headers={
            "X-Tenant-Slug": world.tenant_b.slug,
            "Authorization": f"Bearer {token_client_a}",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Los productos listados deben pertenecer a Empresa B
    for item in data.get("items", []):
        assert item["name"] == world.products[1].name


def test_customer_write_on_different_tenant_store_returns_409_mismatch(client, world):
    # Cliente de Empresa A intenta agregar al carrito en la tienda de Empresa B
    token_client_a = make_token(world.customers[0])
    variant_b = world.variants[1]

    world.tenant_b.is_published = True
    world.db.commit()

    resp = client.put(
        f"/api/v1/commerce/cart/items/{variant_b.id}",
        json={"quantity": 1},
        headers={
            "X-Tenant-Slug": world.tenant_b.slug,
            "Authorization": f"Bearer {token_client_a}",
        },
    )
    assert resp.status_code == 409
    assert "store_account_mismatch" in resp.text


def test_unpublished_store_visibility_and_preview(client, world):
    # Marcar Empresa B como no publicada
    world.tenant_b.is_published = False
    world.db.commit()

    # 1. Visitante anónimo -> 404 store_not_published
    resp_anon = client.get(f"/api/v1/public/stores/{world.tenant_b.slug}")
    assert resp_anon.status_code == 404
    assert "store_not_published" in resp_anon.text

    # 2. Admin de Empresa B -> 200 con preview=true
    token_admin_b = make_token(world.admins[1])
    resp_admin_b = client.get(
        f"/api/v1/public/stores/{world.tenant_b.slug}",
        headers={"Authorization": f"Bearer {token_admin_b}"},
    )
    assert resp_admin_b.status_code == 200
    assert resp_admin_b.json()["data"]["preview"] is True

    # 3. Admin de Empresa A -> 404 store_not_published
    token_admin_a = make_token(world.admins[0])
    resp_admin_a = client.get(
        f"/api/v1/public/stores/{world.tenant_b.slug}",
        headers={"Authorization": f"Bearer {token_admin_a}"},
    )
    assert resp_admin_a.status_code == 404


def test_public_stores_directory_filters(client, world):
    world.tenant_a.is_published = True
    world.tenant_a.status = "ACTIVA"
    world.tenant_a.is_sandbox = False

    world.tenant_b.is_published = False  # No publicada
    world.db.commit()

    resp = client.get("/api/v1/public/stores")
    assert resp.status_code == 200
    slugs = [x["slug"] for x in resp.json()["data"]["items"]]
    assert world.tenant_a.slug in slugs
    assert world.tenant_b.slug not in slugs


def test_tenant_a_patch_does_not_affect_tenant_b(client, world):
    token_admin_a = make_token(world.admins[0])

    # Empresa A configura su marca
    resp = client.patch(
        "/api/v1/tenant/storefront",
        json={"brand_color": "#123456", "slogan": "Moda Elegante A"},
        headers={"Authorization": f"Bearer {token_admin_a}"},
    )
    assert resp.status_code == 200

    # Verificar que Empresa B no cambió
    world.db.refresh(world.tenant_b)
    assert world.tenant_b.brand_color != "#123456"
    assert world.tenant_b.slogan != "Moda Elegante A"


def test_publish_without_logo_returns_409_with_requirements(client, world):
    token_admin_a = make_token(world.admins[0])

    world.tenant_a.logo_url = None
    world.db.commit()

    resp = client.post(
        "/api/v1/tenant/storefront/publish",
        headers={"Authorization": f"Bearer {token_admin_a}"},
    )
    assert resp.status_code == 409
    assert "publish_requirements" in resp.text
    body = resp.json()
    assert "logo" in body["error"]["details"]["missing"]


def test_public_payment_methods_mask_account_number(client, world):
    # Configurar método de cobro con cuenta bancaria
    method = TenantPaymentMethodModel(
        tenant_id=world.tenant_a.id,
        kind="TRANSFER",
        label="Banco Fassil",
        bank_name="Banco Fassil",
        account_holder="Moda A SRL",
        account_number="1234567890",
        is_active=True,
    )
    world.db.add(method)
    world.tenant_a.is_published = True
    world.db.commit()

    resp = client.get(f"/api/v1/public/stores/{world.tenant_a.slug}")
    assert resp.status_code == 200
    methods = resp.json()["data"]["payment_methods_public"]
    assert len(methods) >= 1
    found = next(m for m in methods if m["label"] == "Banco Fassil")
    assert found["account_number"] == "••••••7890"


def test_payment_instructions_for_other_user_order_returns_404(client, world):
    token_client_b = make_token(world.customers[1])

    # Crear pedido de Cliente A
    order_a = OrderModel(
        tenant_id=world.tenant_a.id,
        user_id=world.customers[0].id,
        number="FS-TEST-9999",
        customer_email="cliente0@example.com",
        branch_id=world.branches[0].id,
        status="pending_payment",
        payment_method="transfer",
        currency="BOB",
        total=150.0,
    )
    world.db.add(order_a)
    world.db.commit()

    # Cliente B intenta consultar las instrucciones de pago del pedido de Cliente A
    resp = client.get(
        f"/api/v1/commerce/orders/{order_a.id}/payment-instructions",
        headers={"Authorization": f"Bearer {token_client_b}"},
    )
    assert resp.status_code == 404
