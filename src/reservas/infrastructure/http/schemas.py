from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, model_validator


class ReservaItemInput(BaseModel):
    variant_id: UUID
    quantity: int = Field(default=1, ge=1, le=10)


class CrearReservaRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    branch_id: UUID
    scheduled_at: datetime
    items: list[ReservaItemInput] = Field(min_length=1, max_length=20)
    notes: str | None = Field(default=None, max_length=1000)
    client_key: str | None = Field(
        default=None,
        max_length=64,
        description="Clave idempotente generada por el cliente para el mismo intento.",
    )

    origin: Literal["ONLINE", "OFFLINE"] = "ONLINE"
    device_id: str | None = Field(default=None, min_length=1, max_length=64)
    client_created_at: datetime | None = None
    customer_id: UUID | None = None

    @model_validator(mode="after")
    def offline_requirements(self):
        if self.origin == "OFFLINE" and (not self.client_key or not self.device_id):
            raise ValueError("Una reserva sin conexión requiere client_key y device_id.")
        return self


class EstadoReservaUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    status: Literal["confirmed", "ready", "attended", "cancelled"]
    note: str = Field(default="", max_length=1000)
