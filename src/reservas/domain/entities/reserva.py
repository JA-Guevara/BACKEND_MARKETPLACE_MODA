import uuid
from dataclasses import dataclass, field
from datetime import datetime


TRANSITIONS: dict[str, set[str]] = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"ready", "cancelled"},
    "ready": {"attended", "cancelled"},
}


@dataclass(frozen=True, slots=True)
class Reserva:
    id: uuid.UUID
    user_id: uuid.UUID
    branch_id: uuid.UUID
    status: str
    scheduled_at: datetime
    items: list = field(default_factory=list)
    notes: str | None = None
