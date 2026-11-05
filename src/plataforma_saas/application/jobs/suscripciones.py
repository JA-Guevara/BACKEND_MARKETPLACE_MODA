from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel, SubscriptionNoticeModel


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def calcular_lifecycle_state(sub: SubscriptionModel, ahora: datetime | None = None) -> str:
    if ahora is None:
        ahora = datetime.now(timezone.utc)
    else:
        ahora = _as_utc(ahora)

    hoy = ahora.date()

    if sub.canceled_at is not None or sub.status == "CANCELADA":
        return "canceled"

    ro_since = _as_utc(sub.read_only_since)
    if ro_since is not None:
        if ahora > ro_since + timedelta(days=30):
            return "canceled"
        return "read_only"

    grace_until = _as_utc(sub.grace_until)
    if grace_until is not None:
        if ahora > grace_until:
            return "read_only"
        return "grace"

    if sub.status == "SUSPENDIDA":
        return "suspended"

    # Si la fecha de fin ya pasó pero aún no se asignó grace_until:
    if hoy > sub.end_date:
        grace_end_dt = datetime.combine(sub.end_date + timedelta(days=3), datetime.min.time(), tzinfo=timezone.utc)
        if ahora <= grace_end_dt + timedelta(days=1):
            return "grace"
        return "read_only"

    days_left = (sub.end_date - hoy).days
    if 0 <= days_left <= 7:
        return "expiring"

    return "active"


def proximo_aviso(sub: SubscriptionModel, ahora: datetime | None = None) -> str | None:
    state = calcular_lifecycle_state(sub, ahora)
    if ahora is None:
        ahora = datetime.now(timezone.utc)
    else:
        ahora = _as_utc(ahora)

    hoy = ahora.date()
    days_left = (sub.end_date - hoy).days

    if state == "active":
        return "before_7d"
    if state == "expiring":
        if days_left > 3:
            return "before_3d"
        if days_left > 1:
            return "before_1d"
        return "grace"
    if state == "grace":
        return "read_only"
    if state == "read_only":
        return "canceled"
    return None


class CicloSuscripcion:
    def __init__(self, db: Session):
        self.db = db

    def avisar_por_vencer(self, ahora: datetime) -> int:
        ahora = _as_utc(ahora)
        hoy = ahora.date()

        subs = self.db.scalars(
            select(SubscriptionModel).where(
                SubscriptionModel.closed_at.is_(None),
                SubscriptionModel.status == "ACTIVA",
            )
        ).all()

        count = 0
        for sub in subs:
            days_left = (sub.end_date - hoy).days
            if not (0 <= days_left <= 7):
                continue

            notices_due = []
            if days_left <= 7:
                notices_due.append("before_7d")
            if days_left <= 3:
                notices_due.append("before_3d")
            if days_left <= 1:
                notices_due.append("before_1d")

            for kind in notices_due:
                existing = self.db.scalar(
                    select(SubscriptionNoticeModel).where(
                        SubscriptionNoticeModel.subscription_id == sub.id,
                        SubscriptionNoticeModel.kind == kind,
                        SubscriptionNoticeModel.period_end == sub.end_date,
                    )
                )
                if not existing:
                    notice = SubscriptionNoticeModel(
                        id=uuid4(),
                        subscription_id=sub.id,
                        kind=kind,
                        period_end=sub.end_date,
                        sent_at=ahora,
                    )
                    self.db.add(notice)
                    count += 1

        if count > 0:
            self.db.flush()
        return count

    def pasar_a_gracia(self, ahora: datetime) -> int:
        ahora = _as_utc(ahora)
        hoy = ahora.date()

        subs = self.db.scalars(
            select(SubscriptionModel).where(
                SubscriptionModel.closed_at.is_(None),
                SubscriptionModel.status == "ACTIVA",
                SubscriptionModel.end_date < hoy,
                SubscriptionModel.grace_until.is_(None),
            )
        ).all()

        count = 0
        for sub in subs:
            sub.grace_until = ahora + timedelta(days=3)
            existing = self.db.scalar(
                select(SubscriptionNoticeModel).where(
                    SubscriptionNoticeModel.subscription_id == sub.id,
                    SubscriptionNoticeModel.kind == "grace",
                    SubscriptionNoticeModel.period_end == sub.end_date,
                )
            )
            if not existing:
                self.db.add(
                    SubscriptionNoticeModel(
                        id=uuid4(),
                        subscription_id=sub.id,
                        kind="grace",
                        period_end=sub.end_date,
                        sent_at=ahora,
                    )
                )
            count += 1

        if count > 0:
            self.db.flush()
        return count

    def pasar_a_solo_lectura(self, ahora: datetime) -> int:
        ahora = _as_utc(ahora)
        hoy = ahora.date()

        subs = self.db.scalars(
            select(SubscriptionModel).where(
                SubscriptionModel.closed_at.is_(None),
                SubscriptionModel.read_only_since.is_(None),
                SubscriptionModel.status != "CANCELADA",
            )
        ).all()

        count = 0
        for sub in subs:
            grace_until = _as_utc(sub.grace_until)
            es_vencida = False
            if grace_until is not None and ahora > grace_until:
                es_vencida = True
            elif grace_until is None and sub.end_date < hoy:
                grace_limit = datetime.combine(sub.end_date + timedelta(days=3), datetime.min.time(), tzinfo=timezone.utc)
                if ahora > grace_limit + timedelta(days=1):
                    es_vencida = True

            if es_vencida:
                sub.read_only_since = ahora
                sub.status = "VENCIDA"
                existing = self.db.scalar(
                    select(SubscriptionNoticeModel).where(
                        SubscriptionNoticeModel.subscription_id == sub.id,
                        SubscriptionNoticeModel.kind == "read_only",
                        SubscriptionNoticeModel.period_end == sub.end_date,
                    )
                )
                if not existing:
                    self.db.add(
                        SubscriptionNoticeModel(
                            id=uuid4(),
                            subscription_id=sub.id,
                            kind="read_only",
                            period_end=sub.end_date,
                            sent_at=ahora,
                        )
                    )
                count += 1

        if count > 0:
            self.db.flush()
        return count

    def pasar_a_cancelada(self, ahora: datetime) -> int:
        ahora = _as_utc(ahora)

        subs = self.db.scalars(
            select(SubscriptionModel).where(
                SubscriptionModel.closed_at.is_(None),
                SubscriptionModel.read_only_since.is_not(None),
                SubscriptionModel.canceled_at.is_(None),
            )
        ).all()

        count = 0
        for sub in subs:
            ro_since = _as_utc(sub.read_only_since)
            if ro_since and ahora > ro_since + timedelta(days=30):
                sub.canceled_at = ahora
                sub.status = "CANCELADA"
                sub.data_retention_until = ahora + timedelta(days=30)
                existing = self.db.scalar(
                    select(SubscriptionNoticeModel).where(
                        SubscriptionNoticeModel.subscription_id == sub.id,
                        SubscriptionNoticeModel.kind == "canceled",
                        SubscriptionNoticeModel.period_end == sub.end_date,
                    )
                )
                if not existing:
                    self.db.add(
                        SubscriptionNoticeModel(
                            id=uuid4(),
                            subscription_id=sub.id,
                            kind="canceled",
                            period_end=sub.end_date,
                            sent_at=ahora,
                        )
                    )
                count += 1

        if count > 0:
            self.db.flush()
        return count

    def reactivar(self, subscription: SubscriptionModel, actor=None) -> SubscriptionModel:
        subscription.grace_until = None
        subscription.read_only_since = None
        subscription.canceled_at = None
        subscription.data_retention_until = None
        subscription.status = "ACTIVA"
        if actor:
            subscription.changed_by = getattr(actor, "id", None)
        self.db.flush()
        return subscription
