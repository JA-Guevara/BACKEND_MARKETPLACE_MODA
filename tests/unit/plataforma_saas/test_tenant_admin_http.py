from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.plataforma_saas.infrastructure.models.support_session import SupportSessionModel
from src.ventas_pagos.infrastructure.models import OrderModel


def test_get_tenant_dashboard_metricas_hoy(world):
    tenant_a = world.tenants[0]

    # Crear 2 órdenes de hoy (100 y 250)
    o1 = OrderModel(
        tenant_id=tenant_a.id,
        number="ORD-H1",
        user_id=world.customers[0].id,
        sales_channel="web",
        customer_email="cliente@example.com",
        branch_id=world.branches[0].id,
        status="delivered",
        payment_status="paid",
        payment_method="manual",
        total=Decimal("100.00"),
        subtotal=Decimal("100.00"),
        currency="BOB",
        address={},
        items=[],
        created_at=datetime.now(timezone.utc),
    )
    o2 = OrderModel(
        tenant_id=tenant_a.id,
        number="ORD-H2",
        user_id=world.customers[0].id,
        sales_channel="pos",
        customer_email="cliente@example.com",
        branch_id=world.branches[0].id,
        status="delivered",
        payment_status="paid",
        payment_method="cash",
        total=Decimal("250.00"),
        subtotal=Decimal("250.00"),
        currency="BOB",
        address={},
        items=[],
        created_at=datetime.now(timezone.utc),
    )
    world.db.add_all([o1, o2])
    world.db.commit()

    resp = world.client.get(
        "/api/v1/tenant/dashboard",
        headers=world.headers(world.admins[0]),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert Decimal(str(data["sales_today"])) == Decimal("350.00")
    assert data["orders_today"] == 2
    assert len(data["recent_orders"]) >= 2


def test_get_tenant_dashboard_sucursal_ajena_404(world):
    # Pedir dashboard con la sucursal de tenant B usando sesión de admin A
    sucursal_b = world.branches[1]
    resp = world.client.get(
        f"/api/v1/tenant/dashboard?branch_id={sucursal_b.id}",
        headers=world.headers(world.admins[0]),
    )
    assert resp.status_code == 404


def test_patch_tenant_profile_validaciones_y_bitacora(world):
    # 1. Campo no permitido tax_id -> 422
    resp_inv = world.client.patch(
        "/api/v1/tenant/profile",
        headers=world.headers(world.admins[0]),
        json={"tax_id": "1"},
    )
    assert resp_inv.status_code == 422

    # 2. trade_name válido -> 200
    resp_ok = world.client.patch(
        "/api/v1/tenant/profile",
        headers=world.headers(world.admins[0]),
        json={"trade_name": "Moda C."},
    )
    assert resp_ok.status_code == 200, resp_ok.text
    data = resp_ok.json()["data"]
    assert data["trade_name"] == "Moda C."

    # Verificar evento de bitácora
    world.db.expire_all()
    ev = (
        world.db.query(AuditEventModel)
        .filter(
            AuditEventModel.action == "tenant.profile_updated",
            AuditEventModel.tenant_id == world.tenants[0].id,
        )
        .first()
    )
    assert ev is not None


def test_get_tenant_support_sessions(world):
    tenant_a = world.tenants[0]
    tenant_b = world.tenants[1]

    # Sesión para tenant A
    s_a = SupportSessionModel(
        id=uuid4(),
        tenant_id=tenant_a.id,
        platform_user_id=world.platform.id,
        reason="Asistencia técnica sucursal",
        duration_minutes=30,
        started_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    # Sesión para tenant B
    s_b = SupportSessionModel(
        id=uuid4(),
        tenant_id=tenant_b.id,
        platform_user_id=world.platform.id,
        reason="Asistencia B",
        duration_minutes=30,
        started_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    world.db.add_all([s_a, s_b])
    world.db.commit()

    resp = world.client.get(
        "/api/v1/tenant/support-sessions",
        headers=world.headers(world.admins[0]),
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(s_a.id)
    assert items[0]["platform_user_name"] == "Admin Plataforma"


def test_cajero_sin_permiso_patch_403(world):
    # Un cajero no tiene permiso tenant_profile.write
    cajero = world.db.query(world.customers[0].__class__).filter(
        world.customers[0].__class__.email == f"cliente0@example.com"
    ).first()
    # Asignar rol cajero
    cajero.roles = [world.cashier_role]
    world.db.commit()

    resp = world.client.patch(
        "/api/v1/tenant/profile",
        headers=world.headers(cajero),
        json={"trade_name": "Intento"},
    )
    assert resp.status_code == 403
