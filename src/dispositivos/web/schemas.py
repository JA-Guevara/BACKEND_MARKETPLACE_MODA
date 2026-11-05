from datetime import datetime
import uuid
from pydantic import BaseModel, Field


class DeviceOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    device_id: str
    platform: str
    label: str | None = None
    user_id: uuid.UUID | None = None
    user_name: str | None = None
    branch_id: uuid.UUID | None = None
    branch_name: str | None = None
    app_version: str | None = None
    first_seen_at: datetime
    last_snapshot_at: datetime | None = None
    last_sync_at: datetime | None = None
    last_batch_id: uuid.UUID | None = None
    status: str
    blocked_at: datetime | None = None
    block_reason: str | None = None
    rejected_attempts: int = 0
    last_rejected_at: datetime | None = None

    model_config = {"from_attributes": True}


class DeviceDetailOut(DeviceOut):
    recent_activity: list[dict] = Field(default_factory=list)


class DeviceBlockIn(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
    revoke_sessions: bool = False


class DeviceUnblockIn(BaseModel):
    reason: str | None = None


class DeviceUpdateIn(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)
