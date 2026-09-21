"""Trabajo de generación de la foto IA del probador.

Guarda lo mínimo para que el proceso sea auditable y recuperable: a dónde
apunta la foto de la persona, de qué prenda y color, el proveedor usado, el
resultado y hasta cuándo vive. La foto de la persona se elimina al cancelar o
con la expiración: no se retiene más de lo necesario.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.tryon_ai_jobs.domain import (
    ESTADO_CANCELADO,
    ESTADO_ENCUESTO,
    ESTADO_EXPIRADO,
    ESTADO_FALLIDO,
    ESTADO_PROCESANDO,
)


class TryOnJobModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tryon_ai_jobs"

    # Quién pidió la foto: también es el dueño de la consulta, la cancelación y
    # la eliminación. Nadie más puede verla.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    color_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("colors.id", ondelete="RESTRICT"), index=True
    )
    garment_type: Mapped[str | None] = mapped_column(String(40))
    body_region: Mapped[str | None] = mapped_column(String(20))

    # Foto de la persona, la prenda recortada usada y el resultado.
    person_photo_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    garment_image_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    result_url: Mapped[str | None] = mapped_column(String(1000))

    status: Mapped[str] = mapped_column(
        String(20), default=ESTADO_ENCUESTO, nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_simulation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)