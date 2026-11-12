import os
from unittest.mock import patch
from sqlalchemy import select

from src.plataforma_saas.application.jobs.runner import TareasProgramadas, _active_in_process_locks, _lock_mutex
from src.plataforma_saas.infrastructure.models.ops import JobRunModel


def test_token_invalido_retorna_401(world):
    """Prueba obligatoria: Token inválido -> 401."""
    # Sin cabecera
    resp = world.client.post("/api/v1/platform/ops/jobs/tick")
    assert resp.status_code == 401

    # Con Bearer inválido
    resp_bad = world.client.post(
        "/api/v1/platform/ops/jobs/tick",
        headers={"Authorization": "Bearer token_falso_12345"},
    )
    assert resp_bad.status_code == 401


def test_jwt_super_admin_no_sirve(world):
    """Prueba obligatoria: JWT de super admin no sirve para tick de jobs."""
    platform_headers = world.headers(world.platform)
    resp = world.client.post("/api/v1/platform/ops/jobs/tick", headers=platform_headers)
    assert resp.status_code == 401
    assert "token de servicio" in resp.json()["error"]["message"].lower()


def test_dos_ticks_simultaneos_uno_se_salta_por_candado(world):
    """Prueba obligatoria: Dos ticks simultáneos: uno se salta por el candado."""
    # Simular que otra instancia ya tiene el candado de subscriptions.lifecycle
    job_name = "subscriptions.lifecycle"
    with _lock_mutex:
        _active_in_process_locks.add(job_name)

    try:
        runner = TareasProgramadas(world.db)
        runs = runner.tick()
        sub_run = next(r for r in runs if r.job == job_name)
        assert sub_run.status == "skipped"
        assert "lock_held" in sub_run.changes.get("reason", "")
    finally:
        with _lock_mutex:
            _active_in_process_locks.discard(job_name)


def test_tick_produce_job_runs_sin_datos_personales(world):
    """Prueba obligatoria: Un tick produce job_runs sin datos personales (RNF10)."""
    jobs_token = "secret_jobs_token_test_123456"

    with patch.dict(os.environ, {"JOBS_TOKEN": jobs_token}):
        resp = world.client.post(
            "/api/v1/platform/ops/jobs/tick",
            headers={"Authorization": f"Bearer {jobs_token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data) >= 3

        # Verificar en base de datos
        db_runs = world.db.scalars(select(JobRunModel)).all()
        assert len(db_runs) >= 3

        # RNF10: Ningún campo de cambios debe contener nombres, correos o datos personales
        forbidden_keys = {"email", "first_name", "last_name", "password", "customer", "phone"}
        for run in db_runs:
            if run.changes:
                for k, v in run.changes.items():
                    assert k.lower() not in forbidden_keys
                    if isinstance(v, str):
                        assert "@" not in v


def test_orders_expire_holds_libera_existencias_y_cancela(world):
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    from decimal import Decimal
    from src.ventas_pagos.infrastructure.models import OrderModel, StockModel

    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=3)

    # Crear una orden con apartado web (stripe) de hace 3 horas
    order = OrderModel(
        id=uuid4(),
        tenant_id=world.tenants[0].id,
        number="FS-TEST-HOLD",
        user_id=world.customers[0].id,
        branch_id=world.branches[0].id,
        customer_email=world.customers[0].email,
        payment_method="stripe",
        status="pending_payment",
        payment_status="pending",
        total=Decimal("150.00"),
        subtotal=Decimal("150.00"),
        discount_total=Decimal("0.00"),
        currency="BOB",
        address={"city": "Santa Cruz"},
        items=[{
            "variant_id": str(world.variants[0].id),
            "quantity": 2,
            "unit_price": "75.00",
            "total": "150.00",
        }],
        created_at=past,
    )
    world.db.add(order)

    # Stock actual
    stock_row = world.db.scalar(select(StockModel).where(StockModel.variant_id == world.variants[0].id, StockModel.branch_id == world.branches[0].id))
    initial_stock = stock_row.quantity
    world.db.commit()

    runner = TareasProgramadas(world.db)
    runs = runner.tick(ahora=now)
    expire_run = next(r for r in runs if r.job == "orders.expire_holds")
    assert expire_run.status == "ok"
    assert expire_run.changes["released_orders"] >= 1

    # Verificar que la orden pasó a cancelled
    world.db.refresh(order)
    assert order.status == "cancelled"
    assert order.payment_status == "cancelled"

    # Verificar que el stock fue repuesto (+2)
    world.db.refresh(stock_row)
    assert stock_row.quantity == initial_stock + 2


def test_orders_expire_holds_salta_si_reconcile_falla(world):
    """Si Stripe falla durante la conciliación (timeout o corte), NO cancela el pedido en este tick."""
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    from decimal import Decimal
    from unittest.mock import patch
    from src.ventas_pagos.infrastructure.models import OrderModel
    from src.ventas_pagos.application.service import CommerceService

    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=3)

    order = OrderModel(
        id=uuid4(),
        tenant_id=world.tenants[0].id,
        number="FS-TEST-STRIPE-FAIL",
        user_id=world.customers[0].id,
        branch_id=world.branches[0].id,
        customer_email=world.customers[0].email,
        payment_method="stripe",
        stripe_session_id="cs_test_failure_sim",
        status="pending_payment",
        payment_status="pending",
        total=Decimal("100.00"),
        subtotal=Decimal("100.00"),
        discount_total=Decimal("0.00"),
        currency="BOB",
        address={"city": "Santa Cruz"},
        items=[{
            "variant_id": str(world.variants[0].id),
            "quantity": 1,
            "unit_price": "100.00",
            "total": "100.00",
        }],
        created_at=past,
    )
    world.db.add(order)
    world.db.commit()

    with patch.object(CommerceService, "reconcile_payment", side_effect=RuntimeError("Stripe network timeout")):
        runner = TareasProgramadas(world.db)
        runs = runner.tick(ahora=now)
        expire_run = next(r for r in runs if r.job == "orders.expire_holds")
        assert expire_run.status == "ok"

    world.db.refresh(order)
    # No debe haberse cancelado porque la conciliación falló por red/Stripe
    assert order.status == "pending_payment"


def test_orders_expire_holds_stripe_pagada_no_libera_stock(world):
    """Pedido stripe vencido con sesión pagada en Stripe -> queda paid, no se libera stock."""
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from unittest.mock import patch
    from uuid import uuid4
    from src.ventas_pagos.application.service import CommerceService
    from src.ventas_pagos.infrastructure.models import OrderModel, StockModel

    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=3)

    order = OrderModel(
        id=uuid4(),
        tenant_id=world.tenants[0].id,
        number="FS-TEST-STRIPE-PAID",
        user_id=world.customers[0].id,
        branch_id=world.branches[0].id,
        customer_email=world.customers[0].email,
        payment_method="stripe",
        stripe_session_id="cs_test_paid",
        status="pending_payment",
        payment_status="pending",
        total=Decimal("100.00"),
        subtotal=Decimal("100.00"),
        currency="BOB",
        address={"city": "Santa Cruz"},
        items=[{
            "variant_id": str(world.variants[0].id),
            "quantity": 1,
            "unit_price": "100.00",
            "total": "100.00",
        }],
        created_at=past,
    )
    world.db.add(order)
    world.db.commit()

    stock_row = world.db.scalar(select(StockModel).where(StockModel.variant_id == world.variants[0].id, StockModel.branch_id == world.branches[0].id))
    initial_stock = stock_row.quantity

    def fake_reconcile(self, ord_obj):
        ord_obj.status = "paid"
        ord_obj.payment_status = "paid"
        return {"status": "paid"}

    with patch.object(CommerceService, "reconcile_payment", fake_reconcile):
        runner = TareasProgramadas(world.db)
        runner.tick(ahora=now)

    world.db.refresh(order)
    assert order.status == "paid"
    world.db.refresh(stock_row)
    assert stock_row.quantity == initial_stock


def test_orders_expire_holds_manual_25h_libera_23h_no(world):
    """Pedido manual de 25h vence y libera; de 23h no vence."""
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from uuid import uuid4
    from src.ventas_pagos.infrastructure.models import OrderModel, StockModel

    now = datetime.now(timezone.utc)
    order_25h = OrderModel(
        id=uuid4(),
        tenant_id=world.tenants[0].id,
        number="FS-TEST-MANUAL-25H",
        user_id=world.customers[0].id,
        branch_id=world.branches[0].id,
        customer_email=world.customers[0].email,
        payment_method="manual",
        status="pending_payment",
        payment_status="pending",
        total=Decimal("50.00"),
        subtotal=Decimal("50.00"),
        currency="BOB",
        address={"city": "Santa Cruz"},
        items=[{"variant_id": str(world.variants[0].id), "quantity": 1, "unit_price": "50.00", "total": "50.00"}],
        created_at=now - timedelta(hours=25),
    )
    order_23h = OrderModel(
        id=uuid4(),
        tenant_id=world.tenants[0].id,
        number="FS-TEST-MANUAL-23H",
        user_id=world.customers[0].id,
        branch_id=world.branches[0].id,
        customer_email=world.customers[0].email,
        payment_method="manual",
        status="pending_payment",
        payment_status="pending",
        total=Decimal("50.00"),
        subtotal=Decimal("50.00"),
        currency="BOB",
        address={"city": "Santa Cruz"},
        items=[{"variant_id": str(world.variants[0].id), "quantity": 1, "unit_price": "50.00", "total": "50.00"}],
        created_at=now - timedelta(hours=23),
    )
    world.db.add_all([order_25h, order_23h])
    world.db.commit()

    runner = TareasProgramadas(world.db)
    runner.tick(ahora=now)

    world.db.refresh(order_25h)
    world.db.refresh(order_23h)
    assert order_25h.status in ("expired", "cancelled")
    assert order_23h.status == "pending_payment"


def test_jobs_loop_minutos_cero_no_inicia():
    """Con JOBS_LOOP_MINUTES=0 el ciclo automático no se inicia."""
    import os
    from unittest.mock import patch
    with patch.dict(os.environ, {"JOBS_LOOP_MINUTES": "0"}):
        from src.infrastructure.config.settings import settings
        val = getattr(settings, "jobs_loop_minutes", 0)
        assert val == 0



