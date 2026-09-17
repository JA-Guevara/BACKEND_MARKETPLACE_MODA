import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ExperienciaVirtual:
    """Sesión del probador: el recurso ya preparado que usará el dispositivo.

    Incluye la región del cuerpo y los anclajes porque sin ellos el probador
    solo podría superponer la imagen completa, que es el defecto que se corrigió.
    """

    product_id: uuid.UUID
    asset_type: str
    asset_url: str
    color_id: uuid.UUID | None = None
    mode: str = "2.5d"
    mask_url: str | None = None
    model_3d_url: str | None = None
    garment_type: str | None = None
    body_region: str | None = None
    anchor_points: dict | None = field(default=None)
