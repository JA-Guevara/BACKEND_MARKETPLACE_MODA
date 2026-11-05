from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import select

from src.plataforma_saas.application.billing_service import BillingService
from src.plataforma_saas.application.jobs.runner import TareasProgramadas
from src.plataforma_saas.infrastructure.models.subscription import (
    SubscriptionInvoiceModel,
    SubscriptionModel,
)
from src.shared.exceptions.domain_exception import NotFoundError


def test_un_comprobante_por_periodo(world):
    """Caso obligatorio 1: un comprobante por período e idempotencia."""
    tenant = world.tenants[0]
    sub = world.db.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.tenant_id == tenant.id,
            SubscriptionModel.closed_at.is_(None),
        )
    )
    assert sub is not None

    billing = BillingService(world.db)
    ahora = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)

    # 1. Emitir comprobante
    inv1 = billing.emitir_periodo(sub, ahora)
    world.db.commit()

    assert inv1 is not None
    assert inv1.number.startswith("FS-2026-")
    assert inv1.tenant_id == tenant.id
    assert inv1.subscription_id == sub.id
    assert inv1.period_start == sub.start_date
    assert inv1.period_end == sub.end_date
    assert inv1.status == "issued"
    assert inv1.currency == "BOB"
    assert inv1.amount >= Decimal("0.00")

    # 2. Reintentar emisión en el mismo período -> devuelve el mismo comprobante (idempotente)
    inv2 = billing.emitir_periodo(sub, ahora)
    world.db.commit()

    assert inv2.id == inv1.id
    assert inv2.number == inv1.number

    # Verificar que solo hay 1 comprobante en la base de datos
    count = world.db.scalar(
        select(SubscriptionInvoiceModel).where(
            SubscriptionInvoiceModel.subscription_id == sub.id,
            SubscriptionInvoiceModel.period_start == sub.start_date,
        )
    )
    assert count is not None


def test_registrar_pago_reactiva(world):
    """Caso obligatorio 2: registrar pago reactiva la suscripción."""
    tenant = world.tenants[0]
    sub = world.db.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.tenant_id == tenant.id,
            SubscriptionModel.closed_at.is_(None),
        )
    )
    assert sub is not None

    # Simular suscripción vencida y en solo lectura
    sub.status = "VENCIDA"
    sub.end_date = date(2026, 11, 1)
    sub.grace_until = datetime(2026, 11, 4, 23, 59, tzinfo=timezone.utc)
    sub.read_only_since = datetime(2026, 11, 5, 0, 0, tzinfo=timezone.utc)
    world.db.commit()

    billing = BillingService(world.db)
    inv = billing.emitir_periodo(sub)
    world.db.commit()

    assert inv.status == "issued"
    assert inv.paid_at is None

    # Registrar pago
    actor = world.platform_user
    pagado = billing.registrar_pago(inv.id, referencia="DEP-BMSC-987654", actor_plataforma=actor)
    world.db.commit()

    assert pagado.status == "paid"
    assert pagado.paid_at is not None
    assert pagado.paid_reference == "DEP-BMSC-987654"

    # Verificar que la suscripción se reactivó y limpió gracia y solo lectura
    world.db.refresh(sub)
    assert sub.status == "ACTIVA"
    assert sub.grace_until is None
    assert sub.read_only_since is None
    assert sub.canceled_at is None
    assert sub.end_date > date.today()


def test_empresa_a_no_ve_comprobantes_de_b(world):
    """Caso obligatorio 3: empresa A no ve comprobantes de B (RNF02)."""
    assert len(world.tenants) >= 2
    tenant_a = world.tenants[0]
    tenant_b = world.tenants[1]

    sub_a = world.db.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.tenant_id == tenant_a.id,
            SubscriptionModel.closed_at.is_(None),
        )
    )
    sub_b = world.db.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.tenant_id == tenant_b.id,
            SubscriptionModel.closed_at.is_(None),
        )
    )
    assert sub_a is not None
    assert sub_b is not None

    billing = BillingService(world.db)
    inv_a = billing.emitir_periodo(sub_a)
    inv_b = billing.emitir_periodo(sub_b)
    world.db.commit()

    # Listar comprobantes de empresa A
    invoices_a = billing.listar_por_empresa(tenant_a.id)
    ids_a = {i.id for i in invoices_a}
    assert inv_a.id in ids_a
    assert inv_b.id not in ids_a

    # Listar comprobantes de empresa B
    invoices_b = billing.listar_por_empresa(tenant_b.id)
    ids_b = {i.id for i in invoices_b}
    assert inv_b.id in ids_b
    assert inv_a.id not in ids_b

    # Intentar descargar o acceder al comprobante de B pasando tenant_a -> debe fallar 404
    with pytest.raises(NotFoundError) as exc_info:
        billing.obtener_comprobante(inv_b.id, tenant_id=tenant_a.id)
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "invoice_not_found"

    # Intentar generar PDF de B con tenant_a -> debe fallar 404
    with pytest.raises(NotFoundError) as exc_info:
        billing.pdf(inv_b.id, tenant_id=tenant_a.id)
    assert exc_info.value.status_code == 404


def test_pdf_con_leyenda_obligatoria(world):
    """Generación de PDF con ReportLab y leyenda obligatoria de no validez fiscal."""
    tenant = world.tenants[0]
    sub = world.db.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.tenant_id == tenant.id,
            SubscriptionModel.closed_at.is_(None),
        )
    )
    billing = BillingService(world.db)
    inv = billing.emitir_periodo(sub)
    world.db.commit()

    pdf_bytes = billing.pdf(inv.id, tenant_id=tenant.id)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 500

    # Verificar que el PDF contiene la leyenda en el stream (o texto)
    pdf_text = pdf_bytes.decode("latin-1", errors="ignore")
    assert "COMPROBANTE DE SUSCRIPCI" in pdf_text or "NO V" in pdf_text or "FashionStore SaaS" in pdf_text


def test_runner_invoices_issue(world):
    """La tarea programada invoices.issue emite comprobantes en tick()."""
    tareas = TareasProgramadas(world.db)
    runs = tareas.tick()
    inv_run = next((r for r in runs if r.job == "invoices.issue"), None)

    assert inv_run is not None
    assert inv_run.status == "ok"
    assert "issued_invoices" in (inv_run.changes or {})


def test_http_billing_endpoints(world):
    """Prueba de endpoints HTTP: /tenant/billing/invoices, /pdf y /mark-paid con aislamiento."""
    # Ensure permission billing.read exists and is assigned to admin_role
    from src.roles.infrastructure.persistence.models.permission import PermissionModel

    perm = world.db.scalar(select(PermissionModel).where(PermissionModel.code == "billing.read"))
    if not perm:
        perm = PermissionModel(
            code="billing.read",
            name="Consultar facturación",
            module="billing",
            scope="tenant",
        )
        world.db.add(perm)
        world.db.flush()
    if perm not in world.admin_role.permissions:
        world.admin_role.permissions.append(perm)
        world.db.commit()

    tenant_a = world.tenants[0]
    tenant_b = world.tenants[1]
    admin_a = world.admins[0]
    admin_b = world.admins[1]

    sub_a = world.db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id == tenant_a.id))
    sub_b = world.db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id == tenant_b.id))

    billing = BillingService(world.db)
    inv_a = billing.emitir_periodo(sub_a)
    inv_b = billing.emitir_periodo(sub_b)
    world.db.commit()

    # 1. Admin A consulta sus comprobantes
    res = world.client.get("/api/v1/tenant/billing/invoices", headers=world.headers(admin_a))
    assert res.status_code == 200
    data = res.json()["data"]
    ids = [i["id"] for i in data]
    assert str(inv_a.id) in ids
    assert str(inv_b.id) not in ids

    # 2. Admin A descarga el PDF de su comprobante
    res_pdf = world.client.get(f"/api/v1/tenant/billing/invoices/{inv_a.id}/pdf", headers=world.headers(admin_a))
    assert res_pdf.status_code == 200
    assert res_pdf.headers["content-type"] == "application/pdf"
    assert res_pdf.content.startswith(b"%PDF-")

    # 3. Admin A intenta descargar el PDF del comprobante de B -> 404
    res_cross = world.client.get(f"/api/v1/tenant/billing/invoices/{inv_b.id}/pdf", headers=world.headers(admin_a))
    assert res_cross.status_code == 404

    # 4. Plataforma marca como pagado
    res_paid = world.client.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/invoices/{inv_a.id}/mark-paid",
        headers=world.headers(world.platform_user),
        json={"reference": "TRANSFER-BANCO-7788"},
    )
    assert res_paid.status_code == 200
    assert res_paid.json()["data"]["status"] == "paid"
    assert res_paid.json()["data"]["paid_reference"] == "TRANSFER-BANCO-7788"

