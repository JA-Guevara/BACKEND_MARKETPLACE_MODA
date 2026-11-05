"""Promociones y listas personales del cliente.

Estas tablas guardan reglas y preferencias; los importes finales siempre se
recalculan en :mod:`ventas_pagos.application.promotions` desde el servidor.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PromotionTargetModel(Base):
    """Alcance múltiple de una promoción (prenda, variante, categoría, temporada, colección)."""

    __tablename__ = "promotion_targets"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('PRODUCT', 'VARIANT', 'CATEGORY', 'SEASON', 'COLLECTION', 'ALL')",
            name="ck_promotion_targets_type",
        ),
    )

    promotion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("commerce_promotions.id", ondelete="CASCADE"), primary_key=True
    )
    target_type: Mapped[str] = mapped_column(String(12), primary_key=True)
    target_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, index=True)

    promotion: Mapped["PromotionModel"] = relationship(back_populates="targets")


class PromotionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Una campaña automática (sin código) o un cupón (con código)."""

    __tablename__ = "commerce_promotions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_commerce_promotions_tenant_code"),
        CheckConstraint("discount_value >= 0", name="promotion_value_nonnegative"),
        CheckConstraint("minimum_order >= 0", name="promotion_minimum_nonnegative"),
        CheckConstraint("max_uses IS NULL OR max_uses > 0", name="promotion_max_uses_positive"),
        CheckConstraint("per_user_limit IS NULL OR per_user_limit > 0", name="promotion_per_user_positive"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, default=lambda: uuid.UUID("30000000-0000-0000-0000-000000000001"))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), index=True)
    description: Mapped[str | None] = mapped_column(String(500))
    discount_type: Mapped[str] = mapped_column(String(20), nullable=False)  # percent, fixed, clearance, free_shipping
    discount_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    minimum_order: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    customer_scope: Mapped[str] = mapped_column(String(20), default="all", nullable=False)  # all, frequent
    minimum_paid_orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    max_uses: Mapped[int | None] = mapped_column(Integer)
    uses_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    per_user_limit: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    applies_online: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    applies_pos: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    applies_offline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    targets: Mapped[list[PromotionTargetModel]] = relationship(
        "PromotionTargetModel", back_populates="promotion", cascade="all, delete-orphan", lazy="selectin"
    )


class PromotionUseModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "commerce_promotion_uses"
    __table_args__ = (UniqueConstraint("promotion_id", "order_id"),)

    promotion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("commerce_promotions.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("commerce_orders.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    channel: Mapped[str] = mapped_column(String(10), default="ONLINE", nullable=False)  # ONLINE, POS, OFFLINE


class FavoriteModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "commerce_favorites"
    __table_args__ = (UniqueConstraint("user_id", "product_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    stock_alert: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    price_alert: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    observed_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    last_stock_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_price_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
