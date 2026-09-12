import uuid

from pydantic import BaseModel, ConfigDict


class IniciarExperienciaRequest(BaseModel):
    product_id: uuid.UUID


class ExperienciaVirtualResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: uuid.UUID
    asset_type: str
    asset_url: str
