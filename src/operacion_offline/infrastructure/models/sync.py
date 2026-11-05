from datetime import datetime, timezone
import uuid

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class SyncBatchModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sync_batches"
    __table_args__ = (sa.Index("ix_sync_batches_tenant_started", "tenant_id", "started_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received: Mapped[int] = mapped_column(Integer, default=0)
    confirmed: Mapped[int] = mapped_column(Integer, default=0)
    conflicts: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    replays: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    client_version: Mapped[str] = mapped_column(String(40), default="")
    client_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class SyncOperationModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sync_operations"
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", "client_request_id", name="uq_sync_operations_tenant_request"),
        sa.Index("ix_sync_operations_status", "tenant_id", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    client_request_id: Mapped[uuid.UUID] = mapped_column(sa.types.Uuid, nullable=False)
    type: Mapped[str] = mapped_column(String(12))  # SALE, RESERVATION
    status: Mapped[str] = mapped_column(String(10))  # CONFIRMED, CONFLICT, REJECTED, PENDING
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    device_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sync_batches.id", ondelete="CASCADE"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    server_ref: Mapped[uuid.UUID | None] = mapped_column(sa.types.Uuid, nullable=True)
    server_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    message: Mapped[str] = mapped_column(String(300), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    first_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class SyncConflictModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sync_conflicts"
    __table_args__ = (
        sa.Index("ix_sync_conflicts_open", "tenant_id", "branch_id", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    operation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sync_operations.id", ondelete="CASCADE"), unique=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[str] = mapped_column(String(20))  # STOCK, PRICE, SUBSCRIPTION, PRODUCT_INACTIVE
    detail: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10), default="OPEN")  # OPEN, RESOLVED
    resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ADJUST, AUTHORIZE_PRICE, CANCEL, RETRY
    resolution_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
