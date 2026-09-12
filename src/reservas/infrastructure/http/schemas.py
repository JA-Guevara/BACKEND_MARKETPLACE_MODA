from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


class ReservaItemInput(BaseModel):
    variant_id: UUID
    quantity: int = Field(default=1, ge=1, le=10)


class CrearReservaRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    branch_id: UUID
    scheduled_at: datetime
    items: list[ReservaItemInput] = Field(min_length=1, max_length=20)
    notes: str | None = Field(default=None, max_length=1000)


class EstadoReservaUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    status: Literal["confirmed", "ready", "attended", "cancelled"]
    note: str = Field(default="", max_length=1000)
