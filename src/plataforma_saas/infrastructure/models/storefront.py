"""Modelos de tienda pública, métodos de cobro, plantillas de catálogo y solicitudes (RS-3)."""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TenantPaymentMethodModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenant_payment_methods"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # QR, TRANSFER, PAY_IN_STORE, GATEWAY
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    qr_image_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    account_holder: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    instructions: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class CatalogTemplateModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "catalog_templates"

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CatalogTemplateImportModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "catalog_template_imports"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    template_id: Mapped[UUID] = mapped_column(ForeignKey("catalog_templates.id", ondelete="CASCADE"), nullable=False)
    imported_by: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    counts: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class UpgradeRequestModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "upgrade_requests"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)  # PLAN, LIMIT, MODULE
    target: Mapped[str] = mapped_column(String(60), nullable=False)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="ABIERTA", nullable=False)  # ABIERTA, ATENDIDA, RECHAZADA
    handled_by: Mapped[UUID | None] = mapped_column(nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class UsageAlertModel(Base):
    __tablename__ = "usage_alerts"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    limit_code: Mapped[str] = mapped_column(String(40), primary_key=True)
    level: Mapped[int] = mapped_column(SmallInteger, primary_key=True)  # 80 o 100
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
