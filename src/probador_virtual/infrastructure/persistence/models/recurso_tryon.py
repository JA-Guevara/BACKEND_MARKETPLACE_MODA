"""Recurso preparado del probador virtual.

Se guarda por producto y color, no por variante completa: la talla no cambia la
fotografía, pero el color sí. Probar una camiseta negra con la foto de la blanca
no tendría sentido, y si un color no tiene recurso el probador se anuncia como
no disponible para ese color en lugar de mostrar otro.
"""
import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Modo de representación del recurso.
MODO_2_5D = "2.5d"
MODO_3D = "3d"

# Estado de la preparación asistida por IA.
ESTADO_PENDIENTE = "pending"
ESTADO_PROCESANDO = "processing"
ESTADO_LISTO = "ready"
ESTADO_REVISION = "review"
ESTADO_FALLIDO = "failed"
ESTADO_MANUAL = "manual"


class TryOnAssetModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "virtual_tryon_assets"
    __table_args__ = (UniqueConstraint("product_id", "color_id", name="tryon_producto_color"),)

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    color_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("colors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(10), default=MODO_2_5D, nullable=False)

    # La foto comercial sigue siendo la fuente: no se le pide al administrador
    # una segunda imagen preparada a mano.
    source_image_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    transparent_url: Mapped[str | None] = mapped_column(String(1000))
    mask_url: Mapped[str | None] = mapped_column(String(1000))
    model_3d_url: Mapped[str | None] = mapped_column(String(1000))

    garment_type: Mapped[str | None] = mapped_column(String(40))
    body_region: Mapped[str | None] = mapped_column(String(20), index=True)
    anchor_points: Mapped[dict | None] = mapped_column(
        "anchor_points", JSON().with_variant(JSONB, "postgresql")
    )

    ai_status: Mapped[str] = mapped_column(String(20), default=ESTADO_PENDIENTE, nullable=False)
    ai_metadata: Mapped[dict | None] = mapped_column(
        "ai_metadata", JSON().with_variant(JSONB, "postgresql")
    )
    ai_error: Mapped[str | None] = mapped_column(Text)

    # Calidad del resultado automático y su revisión (plan de evolución, Fase 1).
    # El puntaje y la razón permiten decidir qué se publica solo y qué necesita
    # aprobación: una silueta dudosa no aparece sobre la cámara hasta que el
    # administrador la confirma o la descarta.
    quality_score: Mapped[int | None] = mapped_column(Integer)
    quality_reason: Mapped[str | None] = mapped_column(String(120))
    preview_url: Mapped[str | None] = mapped_column(String(1000))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    color: Mapped["ColorModel"] = relationship(lazy="joined")

    @property
    def usable(self) -> bool:
        """El probador solo puede usarlo si está habilitado y tiene recorte y
        región corporal; sin eso volvería al rectángulo con fondo."""
        return bool(
            self.enabled
            and self.body_region
            and (self.transparent_url or self.model_3d_url)
            and self.ai_status in (ESTADO_LISTO, ESTADO_MANUAL)
        )


from src.usuarios_catalogo.infrastructure.models.catalog import ColorModel  # noqa: E402,F401
