import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, Numeric, DateTime, ForeignKey, JSON, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.infrastructure.database.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class StockModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "commerce_stock"
    __table_args__ = (CheckConstraint("quantity >= 0", name="quantity_positive"), UniqueConstraint("variant_id", "branch_id"))
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_variants.id", ondelete="RESTRICT"))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="RESTRICT"))
    quantity: Mapped[int] = mapped_column(Integer, default=0)


class CartItemModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "commerce_cart_items"
    __table_args__ = (UniqueConstraint("user_id", "variant_id"), CheckConstraint("quantity > 0", name="quantity_positive"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_variants.id", ondelete="RESTRICT"))
    quantity: Mapped[int] = mapped_column(Integer)


class OrderModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "commerce_orders"
    number: Mapped[str] = mapped_column(String(40), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    customer_email: Mapped[str] = mapped_column(String(320))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(30), default="pending_payment", index=True)
    payment_status: Mapped[str] = mapped_column(String(30), default="pending")
    payment_method: Mapped[str] = mapped_column(String(30))
    payment_reference: Mapped[str | None] = mapped_column(String(255))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    address: Mapped[dict] = mapped_column(JSON)
    items: Mapped[list] = mapped_column(JSON)
    tracking: Mapped[list] = mapped_column(JSON, default=list)
    carrier: Mapped[str | None] = mapped_column(String(120))
    tracking_number: Mapped[str | None] = mapped_column(String(150))
    stripe_session_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    stripe_url: Mapped[str | None] = mapped_column(String(2000))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, index=True)


class WebhookEventModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "commerce_webhook_events"
    event_id: Mapped[str] = mapped_column(String(255), unique=True)
