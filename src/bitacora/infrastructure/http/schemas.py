import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID | None = None
    tenant_name: str | None = None
    support_session_id: uuid.UUID | None = None
    support_reason: str | None = None
    actor_is_support: bool = False
    actor_user_id: uuid.UUID | None
    actor_name: str | None
    actor_email: str | None
    action: str
    entity_type: str
    entity_id: str | None
    description: str
    metadata_: dict | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
