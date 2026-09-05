import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RefreshTokenModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (UniqueConstraint("jti"), UniqueConstraint("token_hash"))

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jti: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_jti: Mapped[str | None] = mapped_column(String(64))
    created_by_ip: Mapped[str | None] = mapped_column(String(45))
    revoked_by_ip: Mapped[str | None] = mapped_column(String(45))

    user: Mapped["UserModel"] = relationship(back_populates="refresh_tokens")
