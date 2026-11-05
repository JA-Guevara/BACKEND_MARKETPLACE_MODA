import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import CHAR, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.base import Base, UUIDPrimaryKeyMixin


class ReportRequestModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "report_requests"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    prompt_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    prompt_length: Mapped[int] = mapped_column(Integer, nullable=False)
    interpreted_spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    execution_result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    audio_duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="TEXT", nullable=False)
    definition_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="EXECUTED", nullable=False)
    export_format: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rows_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
