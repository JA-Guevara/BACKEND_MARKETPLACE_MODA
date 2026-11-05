import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GarmentExchangeModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "commerce_garment_exchanges"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), index=True
    )
    original_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("commerce_orders.id", ondelete="RESTRICT"), index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    difference_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))
    payment_method: Mapped[str] = mapped_column(String(30), default="none")
    cash_received: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    cash_returned: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="COMPLETED")
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    client_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(unique=True, nullable=True)

    lines: Mapped[list["GarmentExchangeLineModel"]] = relationship(
        back_populates="exchange", cascade="all, delete-orphan", lazy="selectin"
    )


class GarmentExchangeLineModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "commerce_garment_exchange_lines"

    exchange_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("commerce_garment_exchanges.id", ondelete="CASCADE"), index=True
    )
    original_variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    returned_quantity: Mapped[int] = mapped_column(Integer)
    original_unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    new_variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    delivered_quantity: Mapped[int] = mapped_column(Integer)
    new_unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    price_difference: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    exchange: Mapped["GarmentExchangeModel"] = relationship(back_populates="lines")
