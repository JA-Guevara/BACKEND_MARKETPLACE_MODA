import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: str | None
    description: str
    metadata_: dict | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
