from datetime import date, datetime
from uuid import UUID
from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, text
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
    tenant: Mapped[TenantModel] = relationship(back_populates="subscriptions")
    plan: Mapped[PlanModel] = relationship(lazy="joined")
