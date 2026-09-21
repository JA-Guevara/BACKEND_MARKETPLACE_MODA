"""Promociones y listas personales del cliente.

Estas tablas guardan reglas y preferencias; los importes finales siempre se
recalculan en :mod:`ventas_pagos.application.promotions` desde el servidor.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PromotionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Una campaña automática (sin código) o un cupón (con código)."""

    __tablename__ = "commerce_promotions"
    __table_args__ = (
        CheckConstraint("discount_value >= 0", name="promotion_value_nonnegative"),
        CheckConstraint("minimum_order >= 0", name="promotion_minimum_nonnegative"),
        CheckConstraint("max_uses IS NULL OR max_uses > 0", name="promotion_max_uses_positive"),
        CheckConstraint("per_user_limit IS NULL OR per_user_limit > 0", name="promotion_per_user_positive"),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(500))
    discount_type: Mapped[str] = mapped_column(String(20), nullable=False)  # percent, fixed, free_shipping
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
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class PromotionUseModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "commerce_promotion_uses"
    __table_args__ = (UniqueConstraint("promotion_id", "order_id"),)

    promotion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("commerce_promotions.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("commerce_orders.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


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
