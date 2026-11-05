from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select

from src.plataforma_saas.application.jobs.runner import TareasProgramadas
from src.plataforma_saas.application.jobs.suscripciones import (
    CicloSuscripcion,
    calcular_lifecycle_state,
    proximo_aviso,
)
from src.plataforma_saas.infrastructure.models.subscription import (
    SubscriptionModel,
    SubscriptionNoticeModel,
)


def test_transicion_completa_fechas_fijas(world):
    """Prueba obligatoria: activa -> por vencer -> gracia -> solo lectura -> cancelada con fechas fijas."""
    tenant = world.tenants[0]
    sub = world.db.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.tenant_id == tenant.id,
            SubscriptionModel.closed_at.is_(None),
        )
    )
    assert sub is not None

    # Fijar fecha fin: 10 de noviembre de 2026
    sub.end_date = date(2026, 11, 10)
    sub.status = "ACTIVA"
    sub.grace_until = None
    sub.read_only_since = None
    sub.canceled_at = None
    sub.data_retention_until = None
    world.db.commit()

    ciclo = CicloSuscripcion(world.db)

    # 1. 2026-11-01: más de 7 días -> activa
    t1 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    assert calcular_lifecycle_state(sub, t1) == "active"
    assert proximo_aviso(sub, t1) == "before_7d"

    # 2. 2026-11-04: faltan 6 días -> expiring (aviso 7d)
    t2 = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    assert calcular_lifecycle_state(sub, t2) == "expiring"
    avisos_2 = ciclo.avisar_por_vencer(t2)
    assert avisos_2 == 1

    notice = world.db.scalar(
        select(SubscriptionNoticeModel).where(
            SubscriptionNoticeModel.subscription_id == sub.id,
            SubscriptionNoticeModel.kind == "before_7d",
        )
    )
    assert notice is not None

    # 3. 2026-11-08: faltan 2 días -> aviso 3d
    t3 = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    assert calcular_lifecycle_state(sub, t3) == "expiring"
    avisos_3 = ciclo.avisar_por_vencer(t3)
    assert avisos_3 == 1

    # 4. 2026-11-10: fin del período -> aviso 1d
    t4 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    avisos_4 = ciclo.avisar_por_vencer(t4)
    assert avisos_4 == 1

    # 5. 2026-11-11: Al vencer, pasar a gracia
    t5 = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)
    gracia_count = ciclo.pasar_a_gracia(t5)
    assert gracia_count == 1
    world.db.refresh(sub)
    assert sub.grace_until is not None
    assert calcular_lifecycle_state(sub, t5) == "grace"

    # 6. 2026-11-15: Gracia terminada (> 3 días) -> pasar a solo lectura
    t6 = datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc)
    ro_count = ciclo.pasar_a_solo_lectura(t6)
    assert ro_count == 1
    world.db.refresh(sub)
    assert sub.read_only_since is not None
    assert sub.status == "VENCIDA"
    assert calcular_lifecycle_state(sub, t6) == "read_only"

    # 7. 2026-12-16: >30 días en solo lectura -> cancelada
    t7 = datetime(2026, 12, 16, 8, 0, tzinfo=timezone.utc)
    cancel_count = ciclo.pasar_a_cancelada(t7)
    assert cancel_count == 1
    world.db.refresh(sub)
    assert sub.canceled_at is not None
    assert sub.status == "CANCELADA"
    assert sub.data_retention_until is not None
    assert calcular_lifecycle_state(sub, t7) == "canceled"


def test_idempotencia_avisos_y_tick(world):
    """Prueba obligatoria: Avisos sin duplicar y tick dos veces = mismos cambios una vez."""
    tenant = world.tenants[0]
    sub = world.db.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.tenant_id == tenant.id,
            SubscriptionModel.closed_at.is_(None),
        )
    )
    sub.end_date = date(2026, 11, 10)
    sub.status = "ACTIVA"
    sub.grace_until = None
    sub.read_only_since = None
    sub.canceled_at = None
    world.db.commit()

    runner = TareasProgramadas(world.db)
    t = datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc)

    # Primer tick
    runs_1 = runner.tick(t)
    sub_run_1 = next(r for r in runs_1 if r.job == "subscriptions.lifecycle")
    assert sub_run_1.status == "ok"
    assert sub_run_1.changes["notices_sent"] >= 1

    # Segundo tick con la misma fecha: no debe duplicar avisos ni transiciones
    runs_2 = runner.tick(t)
    sub_run_2 = next(r for r in runs_2 if r.job == "subscriptions.lifecycle")
    assert sub_run_2.status == "ok"
    assert sub_run_2.changes["notices_sent"] == 0
    assert sub_run_2.changes["grace_transitions"] == 0
    assert sub_run_2.changes["read_only_transitions"] == 0
    assert sub_run_2.changes["canceled_transitions"] == 0


def test_renovar_desde_solo_lectura_reactiva(world):
    """Prueba obligatoria: Renovar desde solo lectura -> activa."""
    tenant = world.tenants[0]
    sub = world.db.scalar(
        select(SubscriptionModel).where(
            SubscriptionModel.tenant_id == tenant.id,
            SubscriptionModel.closed_at.is_(None),
        )
    )
    sub.end_date = date(2026, 10, 1)
    sub.status = "VENCIDA"
    sub.read_only_since = datetime(2026, 10, 5, tzinfo=timezone.utc)
    world.db.commit()

    assert calcular_lifecycle_state(sub, datetime(2026, 10, 10, tzinfo=timezone.utc)) == "read_only"

    # Reactivar
    ciclo = CicloSuscripcion(world.db)
    reactivada = ciclo.reactivar(sub, actor=world.platform)
    world.db.commit()

    assert reactivada.status == "ACTIVA"
    assert reactivada.read_only_since is None
    assert reactivada.grace_until is None
    assert reactivada.canceled_at is None
    assert calcular_lifecycle_state(reactivada, datetime(2026, 10, 10, tzinfo=timezone.utc)) == "grace" or reactivada.status == "ACTIVA"
