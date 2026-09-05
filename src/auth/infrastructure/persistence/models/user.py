from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.roles.infrastructure.persistence.models.role import user_roles


class UserModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email"), UniqueConstraint("document_number"))

    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    document_number: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    roles: Mapped[list["RoleModel"]] = relationship(
        secondary=user_roles, back_populates="users", lazy="selectin"
    )
    refresh_tokens: Mapped[list["RefreshTokenModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    addresses: Mapped[list["AddressModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


from src.auth.infrastructure.persistence.models.refresh_token import RefreshTokenModel  # noqa: E402,F401
from src.usuarios.infrastructure.persistence.models.usuario import AddressModel  # noqa: E402,F401
