import uuid
from dataclasses import dataclass


@dataclass(slots=True)
class Direccion:
    id: uuid.UUID
    usuario_id: uuid.UUID
    ciudad: str
    direccion: str
    referencia: str | None = None
    es_principal: bool = False
