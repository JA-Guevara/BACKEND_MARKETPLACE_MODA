from datetime import datetime, timezone
import hashlib
import threading
from uuid import uuid4
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.plataforma_saas.application.jobs.suscripciones import CicloSuscripcion
from src.plataforma_saas.infrastructure.models.module import TenantModuleModel
from src.plataforma_saas.infrastructure.models.ops import JobRunModel
from src.plataforma_saas.infrastructure.models.support_session import SupportSessionModel

_active_in_process_locks: set[str] = set()
_lock_mutex = threading.Lock()


def _as_utc(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _advisory_lock_id(name: str) -> int:
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class TareasProgramadas:
    def __init__(self, db: Session):
        self.db = db

    def _acquire_lock(self, job_name: str) -> bool:
        bind = self.db.get_bind()
        if bind.dialect.name == "postgresql":
            lock_id = _advisory_lock_id(job_name)
            res = self.db.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": lock_id}).scalar()
            return bool(res)
        with _lock_mutex:
            if job_name in _active_in_process_locks:
                return False
            _active_in_process_locks.add(job_name)
            return True

    def _release_lock(self, job_name: str) -> None:
        bind = self.db.get_bind()
        if bind.dialect.name == "postgresql":
            lock_id = _advisory_lock_id(job_name)
            try:
                self.db.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": lock_id})
            except Exception:
                pass
        else:
            with _lock_mutex:
                _active_in_process_locks.discard(job_name)

    def _run_job(self, job_name: str, fn, ahora: datetime) -> JobRunModel:
        started_at = datetime.now(timezone.utc)
        if not self._acquire_lock(job_name):
            job_run = JobRunModel(
                id=uuid4(),
                job=job_name,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                status="skipped",
                changes={"reason": "lock_held_by_concurrent_worker"},
                error=None,
            )
            self.db.add(job_run)
            self.db.commit()
            return job_run

        status = "ok"
        changes = None
        error_msg = None
        try:
            with self.db.begin_nested():
                changes = fn(ahora)
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            status = "failed"
            error_msg = str(exc)
        finally:
            self._release_lock(job_name)

        job_run = JobRunModel(
            id=uuid4(),
            job=job_name,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            status=status,
            changes=changes,
            error=error_msg,
        )
        self.db.add(job_run)
        self.db.commit()
        return job_run

    def tick(self, ahora: datetime | None = None) -> list[JobRunModel]:
        from src.infrastructure.database.session import set_rls_context
        set_rls_context(self.db, is_platform=True)
        ahora = _as_utc(ahora)
        runs: list[JobRunModel] = []

        # 1. subscriptions.lifecycle
        def _job_subscriptions(now: datetime) -> dict:
            ciclo = CicloSuscripcion(self.db)
            notices = ciclo.avisar_por_vencer(now)
            grace = ciclo.pasar_a_gracia(now)
            read_only = ciclo.pasar_a_solo_lectura(now)
            canceled = ciclo.pasar_a_cancelada(now)
            return {
                "notices_sent": notices,
                "grace_transitions": grace,
                "read_only_transitions": read_only,
                "canceled_transitions": canceled,
            }

        runs.append(self._run_job("subscriptions.lifecycle", _job_subscriptions, ahora))

        # 2. modules.trials
        def _job_trials(now: datetime) -> dict:
            trials = self.db.scalars(
                select(TenantModuleModel).where(
                    TenantModuleModel.mode == "TRIAL",
                    TenantModuleModel.expires_at < now,
                    TenantModuleModel.revoked_at.is_(None),
                )
            ).all()
            for trial in trials:
                trial.revoked_at = now
            return {"expired_trials": len(trials)}

        runs.append(self._run_job("modules.trials", _job_trials, ahora))

        # 3. support.expire
        def _job_support(now: datetime) -> dict:
            active_sessions = self.db.scalars(
                select(SupportSessionModel).where(
                    SupportSessionModel.ended_at.is_(None),
                    SupportSessionModel.expires_at < now,
                )
            ).all()
            for s in active_sessions:
                s.ended_at = now

            expired_requests = self.db.scalars(
                select(SupportSessionModel).where(
                    SupportSessionModel.status == "pending_approval",
                    SupportSessionModel.request_expires_at.is_not(None),
                    SupportSessionModel.request_expires_at < now,
                )
            ).all()
            for r in expired_requests:
                r.status = "expired"

            return {
                "expired_sessions": len(active_sessions),
                "expired_requests": len(expired_requests),
            }

        runs.append(self._run_job("support.expire", _job_support, ahora))

        # 4. invoices.issue
        def _job_invoices(now: datetime) -> dict:
            from src.plataforma_saas.application.billing_service import BillingService

            billing = BillingService(self.db)
            issued = billing.emitir_invoices_pendientes(now)
            return {"issued_invoices": issued}

        runs.append(self._run_job("invoices.issue", _job_invoices, ahora))

        def _job_webhooks(now):
            from src.integraciones.application.webhooks_service import WebhooksService
            return {"attempted": len(WebhooksService(self.db).entregar_pendientes())}

        runs.append(self._run_job("webhooks.deliver", _job_webhooks, ahora))

        # 6. orders.expire_holds
        def _job_orders_expire_holds(now: datetime) -> dict:
            from datetime import timedelta
            from src.infrastructure.config.settings import settings
            from src.ventas_pagos.infrastructure.models import OrderModel
            from src.ventas_pagos.application.stock_service import StockService
            from src.ventas_pagos.application.service import CommerceService
            from src.ventas_pagos.infrastructure import gateways
            import uuid
            import logging

            logger = logging.getLogger("jobs.orders")
            hold_minutes = getattr(settings, "order_hold_minutes", 120)
            cutoff = now - timedelta(minutes=hold_minutes)

            # Solo apartados en línea no manuales (ej. stripe) vencen tras el plazo configurable
            expired_orders = self.db.scalars(
                select(OrderModel).where(
                    OrderModel.status == "pending_payment",
                    OrderModel.payment_method == "stripe",
                    OrderModel.created_at < cutoff,
                )
            ).all()

            released = 0
            for o in expired_orders:
                commerce_svc = CommerceService(self.db, o.tenant_id)

                # Si tiene sesión de Stripe, conciliar primero antes de cancelar para evitar cancelar pedidos pagados
                if o.stripe_session_id:
                    try:
                        commerce_svc.reconcile_payment(o)
                    except Exception as exc:
                        logger.warning(f"Error al conciliar pedido {o.number} con Stripe: {exc}")
                        continue

                    if o.payment_status == "paid" or o.status == "paid":
                        continue

                    # Cerrar la sesión en Stripe para que el cliente no pueda pagar tras la cancelación
                    try:
                        gateways.stripe_request(
                            "POST",
                            f"checkout/sessions/{o.stripe_session_id}/expire",
                            **gateways.en_cuenta(o.stripe_account_id),
                        )
                    except Exception as exc:
                        logger.warning(f"Error al expirar sesión Stripe de {o.number}: {exc}")

                o.status = "cancelled"
                o.payment_status = "cancelled"
                stock_svc = StockService(self.db, o.tenant_id)

                for item in (o.items or []):
                    try:
                        vid = uuid.UUID(str(item["variant_id"]))
                        qty = int(item.get("quantity", 1))
                        stock_svc.change(
                            variant_id=vid,
                            branch_id=o.branch_id,
                            delta=qty,
                            kind="web_order_hold_release",
                            reason=f"Liberación de existencias por pedido web vencido {o.number}",
                            actor_id=o.user_id,
                            reference=o.number,
                        )
                    except Exception as exc:
                        logger.error(f"Error al reponer stock para item {item} en {o.number}: {exc}")
                        raise

                o.tracking = [
                    *(o.tracking or []),
                    {
                        "status": "cancelled",
                        "note": f"Apartado vencido ({hold_minutes} min); existencias liberadas.",
                        "date": now.isoformat(),
                    },
                ]
                released += 1

            return {"released_orders": released}

        runs.append(self._run_job("orders.expire_holds", _job_orders_expire_holds, ahora))
        return runs
