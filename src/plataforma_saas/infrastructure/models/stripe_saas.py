"""Modelos de Stripe SaaS (migración 0042).

RN-ST1: de la cuenta conectada de cada empresa solo se guarda el id y su estado;
nunca claves secretas. RN-ST4: stripe_events garantiza un solo procesamiento por evento.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.base import Base


class TenantPaymentAccountModel(Base):
    __tablename__ = "tenant_payment_accounts"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'active', 'restricted')", name="status"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    stripe_account_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    charges_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payouts_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    details_submitted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StripeEventModel(Base):
    __tablename__ = "stripe_events"
    __table_args__ = (
        CheckConstraint("source IN ('billing', 'connect')", name="source"),
    )
    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
