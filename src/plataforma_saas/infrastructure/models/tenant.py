from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TenantModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"
    legal_name: Mapped[str] = mapped_column(String(200))
    trade_name: Mapped[str] = mapped_column(String(150))
    tax_id: Mapped[str] = mapped_column(String(30), unique=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    contact_email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVA")
    deactivation_reason: Mapped[str | None] = mapped_column(Text)
    subscriptions: Mapped[list["SubscriptionModel"]] = relationship(back_populates="tenant")
