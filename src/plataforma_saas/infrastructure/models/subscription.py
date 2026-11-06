from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
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
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)

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


class SubscriptionInvoiceModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "subscription_invoices"
    __table_args__ = (
        UniqueConstraint("subscription_id", "period_start", name="uq_subscription_invoices_sub_period"),
        Index("ix_subscription_invoices_tenant_id", "tenant_id"),
        Index("ix_subscription_invoices_subscription_id", "subscription_id"),
    )
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    subscription_id: Mapped[UUID] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="BOB", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="issued", nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    tenant: Mapped[TenantModel] = relationship()
    subscription: Mapped[SubscriptionModel] = relationship()

