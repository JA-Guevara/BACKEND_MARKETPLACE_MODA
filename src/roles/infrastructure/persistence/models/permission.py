import uuid

from sqlalchemy import Boolean, String, Table, Column, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class PermissionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("code"),)

    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    module: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    roles: Mapped[list["RoleModel"]] = relationship(
        secondary=role_permissions, back_populates="permissions"
    )
