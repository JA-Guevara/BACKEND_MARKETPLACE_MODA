import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EmailVerificationTokenModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "email_verification_tokens"
    __table_args__ = (UniqueConstraint("token_hash"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
