from decimal import Decimal
from uuid import UUID
from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PlanModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plans"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    reference_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    duration_days: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    features: Mapped[list["PlanFeatureModel"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class PlanFeatureModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "plan_features"
    __table_args__ = (UniqueConstraint("plan_id", "feature_code"),)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    feature_code: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    limit_value: Mapped[int | None] = mapped_column(Integer)
