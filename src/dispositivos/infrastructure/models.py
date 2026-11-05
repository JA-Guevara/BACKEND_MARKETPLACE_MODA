from datetime import datetime, timezone
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.base import Base, UUIDPrimaryKeyMixin
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel


class DeviceModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "device_id", name="uq_devices_tenant_device"),
        CheckConstraint("platform IN ('PWA', 'ANDROID')", name="ck_devices_platform"),
        CheckConstraint("status IN ('ACTIVO', 'BLOQUEADO')", name="ck_devices_status"),
        Index("ix_devices_tenant_status", "tenant_id", "status"),
        Index("ix_devices_tenant_last_sync", "tenant_id", "last_sync_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    platform: Mapped[str] = mapped_column(String(10), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    app_version: Mapped[str | None] = mapped_column(String(40), nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    last_snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_batch_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ACTIVO", server_default="ACTIVO"
    )
    blocked_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    blocked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    block_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    rejected_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tenant: Mapped[TenantModel] = relationship(TenantModel, lazy="joined", viewonly=True)
    user: Mapped[UserModel | None] = relationship(UserModel, foreign_keys=[user_id], lazy="joined", viewonly=True)
    branch: Mapped[BranchModel | None] = relationship(BranchModel, lazy="joined", viewonly=True)
    blocked_by_user: Mapped[UserModel | None] = relationship(UserModel, foreign_keys=[blocked_by], lazy="joined", viewonly=True)
