from datetime import date, timedelta
from decimal import Decimal
import uuid
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.ventas_pagos.infrastructure.models import OrderModel


def test_get_dashboard_mrr_y_contadores(world):
    # En conftest hay 2 empresas con suscripciones activas:
    # BASICO (350 / 30d) y PROFESIONAL (890 / 30d) => MRR = 1240.00
    resp = world.client.get(
        "/api/v1/platform/dashboard",
        headers=world.headers(world.platform),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert Decimal(str(data["mrr_estimate"])) == Decimal("1240.00")
    assert data["currency"] == "BOB"
    assert data["tenants"]["active"] >= 2
    assert len(data["plan_distribution"]) >= 2


def test_get_dashboard_suscripcion_por_vencer_attention(world):
    # Modificar la suscripción del tenant B para que venza en 5 días
    sub_b = (
        world.db.query(SubscriptionModel)
        .filter(SubscriptionModel.tenant_id == world.tenants[1].id)
        .first()
    )
    sub_b.end_date = date.today() + timedelta(days=5)
    world.db.commit()

    resp = world.client.get(
        "/api/v1/platform/dashboard",
        headers=world.headers(world.platform),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["tenants"]["expiring_7d"] >= 1

    expiring = [it for it in data["attention"] if it["kind"] == "expiring"]
    assert len(expiring) >= 1
    assert any(it["tenant_id"] == str(world.tenants[1].id) for it in expiring)


def test_get_tenant_overview(world):
    tenant_a = world.tenants[0]

    # Crear 2 órdenes para el tenant A
    order1 = OrderModel(
        tenant_id=tenant_a.id,
        number="ORD-001",
        user_id=world.customers[0].id,
        sales_channel="web",
        customer_email="cliente@example.com",
        branch_id=world.branches[0].id,
        status="delivered",
        payment_status="paid",
        payment_method="manual",
        total=Decimal("150.00"),
        subtotal=Decimal("150.00"),
        currency="BOB",
        address={},
        items=[],
    )
    order2 = OrderModel(
        tenant_id=tenant_a.id,
        number="ORD-002",
        user_id=world.customers[0].id,
        sales_channel="pos",
        customer_email="cliente@example.com",
        branch_id=world.branches[0].id,
        status="delivered",
        payment_status="paid",
        payment_method="cash",
        total=Decimal("100.00"),
        subtotal=Decimal("100.00"),
        currency="BOB",
        address={},
        items=[],
    )
    world.db.add_all([order1, order2])
    world.db.commit()

    resp = world.client.get(
        f"/api/v1/platform/tenants/{tenant_a.id}/overview",
        headers=world.headers(world.platform),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["orders_30d"] == 2
    assert Decimal(str(data["sales_30d"])) == Decimal("250.00")
    assert data["online_orders_30d"] == 1
    assert data["pos_orders_30d"] == 1

    quotas = {q["code"]: q for q in data["quotas"]}
    assert "max_active_branches" in quotas
    assert quotas["max_active_branches"]["used"] == 1
    assert quotas["max_active_branches"]["limit"] == 2


def test_get_tenant_users_and_branches(world):
    tenant_a = world.tenants[0]

    # Users
    resp_users = world.client.get(
        f"/api/v1/platform/tenants/{tenant_a.id}/users",
        headers=world.headers(world.platform),
    )
    assert resp_users.status_code == 200, resp_users.text
    users_data = resp_users.json()["data"]
    assert users_data["total"] >= 2
    emails = [u["email"] for u in users_data["items"]]
    assert "admin0@example.com" in emails

    # Branches
    resp_branches = world.client.get(
        f"/api/v1/platform/tenants/{tenant_a.id}/branches",
        headers=world.headers(world.platform),
    )
    assert resp_branches.status_code == 200, resp_branches.text
    branches_data = resp_branches.json()["data"]
    assert len(branches_data) == 1
    assert branches_data[0]["name"] == "Central"
    assert branches_data[0]["city_name"] == "Santa Cruz"
    assert branches_data[0]["cash_points"] == 1


def test_console_forbidden_para_admin_empresa(world):
    # Un admin de empresa no puede consultar rutas de consola de plataforma
    resp = world.client.get(
        "/api/v1/platform/dashboard",
        headers=world.headers(world.admins[0]),
    )
    assert resp.status_code == 403
