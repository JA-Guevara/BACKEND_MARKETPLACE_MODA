import uuid

from pydantic import BaseModel, ConfigDict, Field

from src.probador_virtual.infrastructure.services.anclajes import REGIONES


class IniciarExperienciaRequest(BaseModel):
    product_id: uuid.UUID
    # El recurso depende del color: probarse una camiseta negra con la foto de
    # la blanca no tendría sentido.
    color_id: uuid.UUID | None = None


class PrepararRecursoRequest(BaseModel):
    color_id: uuid.UUID


class AjustarRecursoRequest(BaseModel):
    """Corrección manual de lo que propuso el análisis automático."""

    model_config = ConfigDict(str_strip_whitespace=True)

    body_region: str | None = None
    garment_type: str | None = Field(default=None, max_length=40)
    anchor_points: dict | None = None
    enabled: bool | None = None
    model_3d_url: str | None = Field(default=None, max_length=1000)

    def region_valida(self) -> bool:
        return self.body_region is None or self.body_region in REGIONES


class RecursoTryOnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    color_id: uuid.UUID
    enabled: bool
    mode: str
    source_image_url: str
    transparent_url: str | None
    mask_url: str | None
    model_3d_url: str | None
    garment_type: str | None
    body_region: str | None
    anchor_points: dict | None
    ai_status: str
    ai_metadata: dict | None
    ai_error: str | None


class ExperienciaVirtualResponse(BaseModel):
    """Lo que necesita el probador para trabajar: el recorte, la región del
    cuerpo y los anclajes. Sin esto volvería a superponer la foto completa."""

    model_config = ConfigDict(from_attributes=True)

    product_id: uuid.UUID
    color_id: uuid.UUID | None = None
    mode: str = "2.5d"
    asset_type: str
    asset_url: str
    mask_url: str | None = None
    model_3d_url: str | None = None
    garment_type: str | None = None
    body_region: str | None = None
    anchor_points: dict | None = None
