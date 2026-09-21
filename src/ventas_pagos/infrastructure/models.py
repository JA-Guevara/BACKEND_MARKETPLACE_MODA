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
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    sales_channel: Mapped[str] = mapped_column(String(10), default="web", server_default="web")
    cash_point_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cash_points.id", ondelete="RESTRICT"))
    cashier_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    client_request_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    customer_email: Mapped[str] = mapped_column(String(320))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(30), default="pending_payment", index=True)
    payment_status: Mapped[str] = mapped_column(String(30), default="pending")
    payment_method: Mapped[str] = mapped_column(String(30))
    payment_reference: Mapped[str | None] = mapped_column(String(255))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0), nullable=False)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0), nullable=False)
    discounts: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    coupon_code: Mapped[str | None] = mapped_column(String(50))
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


class StockMovementModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "commerce_stock_movements"
    __table_args__ = (
        CheckConstraint("quantity_before >= 0 AND quantity_after >= 0", name="nonnegative_balances"),
        CheckConstraint("quantity_after = quantity_before + delta", name="balanced_movement"),
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_variants.id", ondelete="RESTRICT"), index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="RESTRICT"), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    quantity_before: Mapped[int] = mapped_column(Integer)
    quantity_after: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(String(500))
    reference: Mapped[str | None] = mapped_column(String(100))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_email: Mapped[str | None] = mapped_column(String(320))


class OrderReturnModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Devolución de prendas de un pedido entregado (CU19).

    Guarda una copia de las prendas devueltas con su precio: el catálogo puede
    cambiar después y el reintegro tiene que corresponder a lo que se cobró.
    """

    __tablename__ = "commerce_order_returns"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("commerce_orders.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="requested", index=True)
    reason: Mapped[str] = mapped_column(String(500))
    items: Mapped[list] = mapped_column(JSON)
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    resolution_note: Mapped[str | None] = mapped_column(String(500))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    #: Evita duplicar la devolución si el cliente reenvía el formulario.
    client_request_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)
