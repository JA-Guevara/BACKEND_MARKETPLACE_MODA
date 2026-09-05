import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class User:
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    is_active: bool = True
    is_verified: bool = False
    role_codes: set[str] = field(default_factory=set)
    locked_until: datetime | None = None
