from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
import pytest
from sqlalchemy import select

from src.plataforma_saas.infrastructure.models.module import PlatformModuleModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from tests.unit.plataforma_saas.conftest import make_token


def test_support_read_only_blocks_mutations_and_allows_reads(client, world):
    # Crear sesión de soporte READ_ONLY
    super_admin_token = make_token(world.platform_user)

    start_payload = {
        "reason": "Auditoría visual de órdenes",
        "duration_minutes": 60,
        "mode": "READ_ONLY",
    }
    resp = client.post(
        f"/api/v1/platform/tenants/{world.tenant_a.id}/support-sessions",
        json=start_payload,
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code in (200, 201)
    session_data = resp.json()["data"]
    support_token = session_data.get("token") or session_data.get("access_token")
    session_id = session_data["session"]["id"]

    # 1. GET permitido en sesión de soporte READ_ONLY
    get_resp = client.get(
        "/api/v1/catalog/products",
        headers={"Authorization": f"Bearer {support_token}"},
    )
    assert get_resp.status_code == 200

    # 2. POST mutante bloqueado con 403 support_read_only
    post_resp = client.post(
        "/api/v1/catalog/admin/products",
        json={"name": "Prenda No Permitida", "slug": "prenda-ro", "base_price": 50.0, "category_id": str(uuid4())},
        headers={"Authorization": f"Bearer {support_token}"},
    )
    assert post_resp.status_code == 403
    assert "support_read_only" in post_resp.text

    # 3. Upgrade a WRITE
    upgrade_resp = client.post(
        f"/api/v1/platform/support-sessions/{session_id}/upgrade",
        json={"reason": "Se requiere corregir un producto"},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert upgrade_resp.status_code == 200
    write_token = upgrade_resp.json()["data"].get("token") or upgrade_resp.json()["data"].get("access_token")

    # 4. Con el nuevo token de escritura, la mutación ya no da support_read_only
    post_write_resp = client.post(
        "/api/v1/catalog/admin/products",
        json={"name": "Prenda Permitida", "slug": "prenda-wr", "base_price": 50.0, "category_id": str(uuid4())},
        headers={"Authorization": f"Bearer {write_token}"},
    )
    assert post_write_resp.status_code != 403 or "support_read_only" not in post_write_resp.text


def test_support_token_cannot_access_platform_endpoints(client, world):
    # Un token de soporte (sea RO o WRITE) tiene tenant_id y no puede acceder a /platform/*
    support_token = make_token(world.admin_a, session_id=uuid4(), read_only=True)

    resp = client.get(
        "/api/v1/platform/tenants",
        headers={"Authorization": f"Bearer {support_token}"},
    )
    assert resp.status_code in (401, 403)


def test_sandbox_preview_opens_write_with_landing_module(client, world):
    super_admin_token = make_token(world.platform_user)

    # Crear tenant sandbox con suscripción activa
    demo_tenant = TenantModel(
        trade_name="FashionStore Demo",
        legal_name="FashionStore Demo S.R.L.",
        tax_id="DEMO-12345",
        slug="demo",
        contact_email="demo@fashionstore.test",
        is_sandbox=True,
        status="ACTIVA",
    )
    world.db.add(demo_tenant)
    world.db.flush()

    sub = SubscriptionModel(
        tenant_id=demo_tenant.id,
        plan_id=world.plans[1].id,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=30),
        status="ACTIVA",
    )
    mod = PlatformModuleModel(
        code="ai_reports",
        name="Reportes con IA",
        kind="ADDON",
        lifecycle="GA",
    )
    world.db.add_all([sub, mod])
    world.db.commit()

    resp = client.post(
        "/api/v1/platform/sandbox/preview",
        json={"module_code": "ai_reports"},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code in (200, 201)
    data = resp.json()["data"]
    assert data["session"]["landing_module"] == "ai_reports"
    assert data["session"]["mode"] == "WRITE"
    assert data["session"]["status"] == "active"
    assert data["access_token"]

    # Verificar que se actualizó last_preview_at del módulo
    world.db.refresh(mod)
    assert mod.last_preview_at is not None


def test_sandbox_prepare_and_reset_reuse_demo_without_touching_other_tenants(client, world):
    route = "/api/v1/platform/sandbox"
    headers = {"Authorization": f"Bearer {make_token(world.platform_user)}"}
    assert client.post(route + "/reset", json={"confirm": False}, headers=headers).status_code == 422

    response = client.post(route + "/reset", json={"confirm": True}, headers=headers)
    assert response.status_code == 200, response.text
    demo = response.json()["data"]
    assert demo["is_active"] and demo["modules"]
    assert demo["branches_count"] == 3
    assert demo["products_count"] == 120

    again = client.post(route + "/reset", json={"confirm": True}, headers=headers)
    assert again.status_code == 200, again.text
    assert again.json()["data"]["tenant_id"] == demo["tenant_id"]
    world.db.refresh(world.product_a)
    assert world.product_a.is_active
