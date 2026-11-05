import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Index,
    JSON,
    String,
    Table,
    Text,
    Uuid,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.roles.infrastructure.persistence.models.permission import PermissionModel


module_permissions = Table(
    "module_permissions",
    Base.metadata,
    Column("module_code", String(40), ForeignKey("platform_modules.code", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Uuid, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    UniqueConstraint("permission_id", name="uq_module_permissions_permission_id"),
)


class ModulePermissionModel(Base):
    __table__ = module_permissions


class PlatformModuleModel(TimestampMixin, Base):
    __tablename__ = "platform_modules"
    __table_args__ = (
        CheckConstraint("kind IN ('BASE', 'ADDON')", name="ck_platform_modules_kind"),
        CheckConstraint("lifecycle IN ('BORRADOR', 'BETA', 'GA', 'RETIRADO')", name="ck_platform_modules_lifecycle"),
    )

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(8), nullable=True)
    kind: Mapped[str] = mapped_column(String(8), default="ADDON", nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(10), default="GA", nullable=False)
    depends_on: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    web_routes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_preview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_preview_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    permissions: Mapped[list["PermissionModel"]] = relationship(
        "PermissionModel",
        secondary=module_permissions,
        lazy="selectin",
    )


class TenantModuleModel(Base):
    __tablename__ = "tenant_modules"
    __table_args__ = (
        CheckConstraint("mode IN ('EXTRA', 'TRIAL', 'BLOQUEADO')", name="ck_tenant_modules_mode"),
        CheckConstraint("mode <> 'TRIAL' OR expires_at IS NOT NULL", name="ck_tenant_modules_trial_expires"),
        Index("uq_tenant_modules_activo", "tenant_id", "module_code", unique=True,
              postgresql_where=text("revoked_at IS NULL"), sqlite_where=text("revoked_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    module_code: Mapped[str] = mapped_column(ForeignKey("platform_modules.code", ondelete="CASCADE"), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc), nullable=False)

    def activo(self, now: datetime) -> bool:
        if self.revoked_at is not None:
            return False
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        starts = self.starts_at
        if starts.tzinfo is None:
            starts = starts.replace(tzinfo=timezone.utc)
        if starts > now:
            return False
        if self.expires_at is None:
            return True
        exp = self.expires_at
        if exp.tzinfo is None and now.tzinfo is not None:
            exp = exp.replace(tzinfo=timezone.utc)
        elif exp.tzinfo is not None and now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return exp > now


class TenantLimitModel(Base):
    __tablename__ = "tenant_limits"
    __table_args__ = (
        CheckConstraint("value >= 0", name="ck_tenant_limits_value_positive"),
        Index("uq_tenant_limits_activo", "tenant_id", "limit_code", unique=True,
              postgresql_where=text("revoked_at IS NULL"), sqlite_where=text("revoked_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    limit_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
