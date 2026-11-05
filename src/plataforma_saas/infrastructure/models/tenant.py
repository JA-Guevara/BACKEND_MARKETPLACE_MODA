from datetime import datetime
from sqlalchemy import Boolean, DateTime, Index, Integer, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TenantModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (Index("uq_tenants_is_sandbox", "is_sandbox", unique=True,
        postgresql_where=text("is_sandbox = true"), sqlite_where=text("is_sandbox = 1")),)
    legal_name: Mapped[str] = mapped_column(String(200))
    trade_name: Mapped[str] = mapped_column(String(150))
    tax_id: Mapped[str] = mapped_column(String(30), unique=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    contact_email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVA")
    deactivation_reason: Mapped[str | None] = mapped_column(Text)
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exchange_days: Mapped[int] = mapped_column(Integer, default=15, server_default="15", nullable=False)

    # RS-3: Campos de tienda pública y marca
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    banner_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    brand_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    slogan: Mapped[str | None] = mapped_column(String(160), nullable=True)
    about: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(30), nullable=True)
    social_links: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    shipping_policy: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    seo_title: Mapped[str | None] = mapped_column(String(70), nullable=True)
    seo_description: Mapped[str | None] = mapped_column(String(160), nullable=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    support_access_mode: Mapped[str] = mapped_column(
        String(20), default="require_approval", server_default="require_approval", nullable=False
    )

    subscriptions: Mapped[list["SubscriptionModel"]] = relationship(back_populates="tenant")
