import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PermissionCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$", max_length=100)
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=255)
    module: str = Field(min_length=2, max_length=50)

    @field_validator("code", "module")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().lower()


class PermissionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=255)
    module: str | None = Field(default=None, min_length=2, max_length=50)


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    module: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RoleCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=50)
    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    permission_ids: list[uuid.UUID] = Field(default_factory=list)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().lower()


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=255)


class SetPermissionsRequest(BaseModel):
    permission_ids: list[uuid.UUID]


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    is_system: bool
    is_active: bool
    permissions: list[PermissionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
