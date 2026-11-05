from datetime import datetime

from sqlalchemy import BigInteger, CHAR, CheckConstraint, DateTime, Index, JSON, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.base import Base, UUIDPrimaryKeyMixin


class PlatformBackup(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "platform_backups"
    __table_args__ = (
        CheckConstraint("verify_status IN ('ok', 'failed', 'pending')", name="verify_status"),
        CheckConstraint(
            "verify_status <> 'ok' OR (sha256 IS NOT NULL AND size_bytes > 0 "
            "AND storage_ref IS NOT NULL AND alembic_revision IS NOT NULL "
            "AND pg_server_version IS NOT NULL AND pg_server_version > 0 AND verify_report IS NOT NULL)",
            name="verified_artifact",
        ),
        UniqueConstraint("sha256", name="uq_platform_backups_sha256"),
        Index("ix_platform_backups_status_finished", "verify_status", text("finished_at DESC")),
        Index(
            "uq_platform_backups_failed_run", "workflow_run_url", unique=True,
            postgresql_where=text("sha256 IS NULL"), sqlite_where=text("sha256 IS NULL"),
        ),
    )

    kind: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(CHAR(64))
    storage_ref: Mapped[str | None] = mapped_column(String(200))
    alembic_revision: Mapped[str | None] = mapped_column(String(40))
    pg_server_version: Mapped[int | None]
    verify_status: Mapped[str] = mapped_column(String(10))
    verify_report: Mapped[dict | None] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
    )
    workflow_run_url: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobRunModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        Index("ix_job_runs_job_started_at", "job", text("started_at DESC")),
    )

    job: Mapped[str] = mapped_column(String(60), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    changes: Mapped[dict | None] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
