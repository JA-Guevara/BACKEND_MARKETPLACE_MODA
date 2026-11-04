import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.base import Base, UUIDPrimaryKeyMixin
from src.plataforma_saas.infrastructure.models.support_session import SupportSessionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel


class AuditEventModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True, nullable=True
    )
    support_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("support_sessions.id", ondelete="SET NULL"), index=True, nullable=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(100), index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSON().with_variant(JSONB, "postgresql")
    )
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )

    actor: Mapped["UserModel | None"] = relationship(UserModel, lazy="joined", viewonly=True)
    support_session: Mapped["SupportSessionModel | None"] = relationship(SupportSessionModel, lazy="joined", viewonly=True)
    tenant: Mapped["TenantModel | None"] = relationship(TenantModel, lazy="joined", viewonly=True)

    @property
    def actor_name(self) -> str | None:
        if self.actor is None:
            return None
        return f"{self.actor.first_name} {self.actor.last_name}".strip()

    @property
    def actor_email(self) -> str | None:
        return self.actor.email if self.actor else None

    @property
    def actor_is_support(self) -> bool:
        return self.support_session_id is not None

    @property
    def support_reason(self) -> str | None:
        return self.support_session.reason if self.support_session else None

    @property
    def tenant_name(self) -> str | None:
        if self.tenant is None:
            return None
        return self.tenant.trade_name or self.tenant.legal_name


EventoBitacoraModel = AuditEventModel
