from datetime import datetime, timezone
from typing import Any
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text, Uuid
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from src.infrastructure.database.base import Base


class ApiKeyModel(Base):
    __tablename__ = "api_keys"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    prefix = Column(String(16), nullable=False)
    key_hash = Column(String(128), nullable=False, index=True)
    scopes = Column(JSON, nullable=False, default=list)
    created_by = Column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class WebhookEndpointModel(Base):
    __tablename__ = "webhook_endpoints"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(String(500), nullable=False)
    secret_enc = Column(LargeBinary, nullable=False)
    events = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    deliveries = relationship("WebhookDeliveryModel", back_populates="endpoint", cascade="all, delete-orphan")


class IntegrationEventModel(Base):
    __tablename__ = "integration_events"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    deliveries = relationship("WebhookDeliveryModel", back_populates="event", cascade="all, delete-orphan")


class WebhookDeliveryModel(Base):
    __tablename__ = "webhook_deliveries"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    endpoint_id = Column(Uuid, ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(Uuid, ForeignKey("integration_events.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt = Column(Integer, nullable=False, default=1)
    status_code = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    endpoint = relationship("WebhookEndpointModel", back_populates="deliveries")
    event = relationship("IntegrationEventModel", back_populates="deliveries")
