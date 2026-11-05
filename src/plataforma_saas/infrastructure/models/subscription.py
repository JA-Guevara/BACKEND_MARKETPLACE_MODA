from datetime import date, datetime
from uuid import UUID
from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.infrastructure.models.plan import PlanModel


class SubscriptionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (Index("uq_subscriptions_tenant_open", "tenant_id", unique=True,
                           postgresql_where=text("closed_at IS NULL"), sqlite_where=text("closed_at IS NULL")),)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("plans.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVA")
    reason: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_only_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[TenantModel] = relationship(back_populates="subscriptions")
    plan: Mapped[PlanModel] = relationship(lazy="joined")


class SubscriptionNoticeModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "subscription_notices"
    __table_args__ = (
        UniqueConstraint("subscription_id", "kind", "period_end", name="uq_subscription_notices_kind_end"),
        Index("ix_subscription_notices_subscription_id", "subscription_id"),
    )
    subscription_id: Mapped[UUID] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    subscription: Mapped[SubscriptionModel] = relationship()
