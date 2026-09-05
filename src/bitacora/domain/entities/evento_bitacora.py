import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class EventoBitacora:
    id: uuid.UUID
    accion: str
    tipo_entidad: str
    descripcion: str
    creado_en: datetime
    actor_usuario_id: uuid.UUID | None = None
    entidad_id: str | None = None
