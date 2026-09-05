import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CityModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cities"
    __table_args__ = (UniqueConstraint("country", "department", "name"),)

    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    country: Mapped[str] = mapped_column(String(100), default="Bolivia", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    branches: Mapped[list["BranchModel"]] = relationship(back_populates="city", lazy="selectin")


class SupplierModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("tax_id"),)

    business_name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    trade_name: Mapped[str | None] = mapped_column(String(180))
    tax_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    contact_name: Mapped[str | None] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class BranchModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("code"), UniqueConstraint("city_id", "name"))

    code: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    city_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cities.id", ondelete="RESTRICT"), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    opening_hours: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    city: Mapped[CityModel] = relationship(back_populates="branches", lazy="joined")
    cash_points: Mapped[list["CashPointModel"]] = relationship(back_populates="branch", lazy="selectin")


class CashPointModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cash_points"
    __table_args__ = (UniqueConstraint("branch_id", "code"),)

    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    branch: Mapped[BranchModel] = relationship(back_populates="cash_points")
