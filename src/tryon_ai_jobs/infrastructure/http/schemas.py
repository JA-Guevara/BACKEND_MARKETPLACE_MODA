import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TryOnJobResponse(BaseModel):
    """Lo que ve quien pidió la foto IA. Incluye el aviso permanente de que es
    una simulación visual y no confirma talla ni ajuste físico."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    color_id: uuid.UUID | None
    garment_type: str | None
    body_region: str | None
    status: str
    provider: str
    result_url: str | None
    error: str | None
    expires_at: datetime | None
    created_at: datetime
    is_simulation: bool
    # Mensaje fijo, no una columna: define la experiencia, no los datos.
    disclaimer: str = (
        "Esta imagen es una simulación visual generada con IA. No confirma talla, "
        "ajuste ni caída física de la prenda."
    )