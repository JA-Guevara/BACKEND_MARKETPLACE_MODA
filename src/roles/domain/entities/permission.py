import uuid
from dataclasses import dataclass


@dataclass(slots=True)
class Permission:
    id: uuid.UUID
    code: str
    name: str
    module: str
    is_active: bool = True
