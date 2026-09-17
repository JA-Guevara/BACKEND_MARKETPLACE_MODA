import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ReservationModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("user_id", "client_key", name="uq_reservations_user_client_key"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    items: Mapped[list] = mapped_column(JSON, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(1000))
    tracking: Mapped[list] = mapped_column(JSON, default=list)
    client_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Las reservas anteriores a esta migración no descontaban existencias.
    # Nunca devolver unidades que no fueron apartadas realmente.
    inventory_held: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
