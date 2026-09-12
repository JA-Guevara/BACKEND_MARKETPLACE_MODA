import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExperienciaVirtual:
    """Sesión de vestidor virtual: qué producto y qué recurso AR se está probando."""

    product_id: uuid.UUID
    asset_type: str
    asset_url: str
