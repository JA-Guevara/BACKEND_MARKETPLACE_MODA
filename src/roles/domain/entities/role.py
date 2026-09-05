import uuid
from dataclasses import dataclass, field


@dataclass(slots=True)
class Role:
    id: uuid.UUID
    code: str
    name: str
    permission_codes: set[str] = field(default_factory=set)
    is_system: bool = False
    is_active: bool = True
