from datetime import datetime
from uuid import UUID
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.infrastructure.database.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class TenantBackupPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenant_backup_policies"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_tenant_backup_policies_tenant"),)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    frequency: Mapped[str] = mapped_column(String(10), default="daily")
    hour: Mapped[int] = mapped_column(Integer, default=3)
    timezone: Mapped[str] = mapped_column(String(80), default="America/La_Paz")
    retention: Mapped[int] = mapped_column(Integer, default=7)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class TenantBackupRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenant_backup_runs"
    __table_args__ = (UniqueConstraint("tenant_id", "request_key", name="uq_tenant_backup_runs_request"),
                      Index("ix_tenant_backup_runs_status_created", "status", "created_at"))
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    requested_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    request_key: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(String(300))
    artifact: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
