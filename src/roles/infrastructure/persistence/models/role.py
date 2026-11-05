import uuid

from sqlalchemy import Boolean, CheckConstraint, String, Table, Column, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.roles.infrastructure.persistence.models.permission import role_permissions


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class RoleModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_roles_tenant_code"),
        CheckConstraint("audience IN ('TENANT', 'PLATFORM')", name="ck_roles_audience"))

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=True, default=None)
    code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    audience: Mapped[str] = mapped_column(String(10), default="TENANT", nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    permissions: Mapped[list["PermissionModel"]] = relationship(
        secondary=role_permissions, back_populates="roles", lazy="selectin"
    )
    users: Mapped[list["UserModel"]] = relationship(
        secondary=user_roles, back_populates="roles"
    )

    @property
    def is_template(self) -> bool:
        return self.tenant_id is None

    @property
    def users_count(self) -> int:
        if hasattr(self, "_users_count"):
            return self._users_count
        try:
            return len(self.users) if self.users else 0
        except Exception:
            return 0

    @users_count.setter
    def users_count(self, value: int) -> None:
        self._users_count = value
