"""Creación de un trabajo de foto IA realista (Fase 3).

La petición valida por qué y vuelve al instante con el trabajo en `queued`: la
generación corre cuando se consulta el estado. Se exige el consentimiento
explícito del cliente, se limita la cantidad de trabajos activos por persona y
la foto de la prenda usada es la del recurso del probador (fondo recortado): la
misma que vería en el espejo en vivo.
"""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.infrastructure.config.settings import settings
from src.probador_virtual.domain.exceptions import SinRecursoARError
from src.probador_virtual.infrastructure.services.virtual_fitting_service import VirtualFittingService
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError
from src.tryon_ai_jobs.domain import ACTIVOS, ESTADO_ENCUESTO
from src.tryon_ai_jobs.infrastructure.persistence.models.tryon_job import TryOnJobModel
from src.usuarios_catalogo.infrastructure.media_storage import store_image
from src.usuarios_catalogo.infrastructure.models.catalog import ProductModel


class CrearTrabajo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def execute(
        self,
        user,
        product_id: uuid.UUID,
        color_id: uuid.UUID | None,
        persona_bytes: bytes,
        consentimiento: bool,
        proveedor: str,
    ) -> TryOnJobModel:
        if not consentimiento:
            raise ValidationError(
                "Para generar la foto realista tenés que aceptar el procesamiento de tu foto."
            )
        producto = self.db.get(ProductModel, product_id)
        if not producto or not producto.is_active or producto.deleted_at:
            raise NotFoundError("Prenda no disponible.")
        if color_id:
            self._validar_color(producto, color_id)

        if self._active_count(user.id) >= settings.tryon_max_active_jobs:
            raise ValidationError(
                f"Ya tenés {settings.tryon_max_active_jobs} fotos IA en curso. "
                "Esperá a que terminen o cancelá una antes de pedir otra."
            )

        prenda_url, prenda_tipo, region = self._prenda_para_la_foto(producto, color_id)
        nombre_persona, _, _ = store_image(
            persona_bytes, Path(settings.media_storage_dir).resolve()
        )
        base = settings.media_public_base_url.rstrip("/")

        plazo = datetime.now(timezone.utc) + timedelta(
            hours=settings.tryon_result_expiration_hours
        )
        trabajo = TryOnJobModel(
            user_id=user.id,
            product_id=producto.id,
            color_id=color_id,
            garment_type=prenda_tipo,
            body_region=region,
            person_photo_url=f"{base}/{nombre_persona}",
            garment_image_url=prenda_url,
            status=ESTADO_ENCUESTO,
            provider=proveedor,
            expires_at=plazo,
            # Solo el proveedor local superpone una imagen; FASHN genera una
            # foto de try-on, aunque ambas siguen siendo orientativas para talla.
            is_simulation=proveedor == "mock",
        )
        self.db.add(trabajo)
        self.db.flush()
        RecordAuditEvent(self.db).execute(
            action="tryon_ai.job_created",
            entity_type="tryon_ai_job",
            entity_id=str(trabajo.id),
            description="Se pidió una foto IA del probador.",
            actor_user_id=user.id,
            metadata={
                "product_id": str(producto.id),
                "color_id": str(color_id) if color_id else None,
                "provider": proveedor,
            },
        )
        self.db.commit()
        self.db.refresh(trabajo)
        return trabajo

    def _validar_color(self, producto: ProductModel, color_id: uuid.UUID) -> None:
        existe = any(
            v.color_id == color_id and v.is_active for v in producto.variants
        )
        if not existe:
            raise ValidationError("Ese color no es una variante activa de la prenda.")

    def _prenda_para_la_foto(
        self, producto: ProductModel, color_id: uuid.UUID | None
    ) -> tuple[str, str | None, str | None]:
        """Prefiere el recorte del probador (transparente) y, si no hay, la foto
        comercial: el proveedor ve la prenda de todas formas."""
        try:
            experiencia = VirtualFittingService(self.db).resolve_asset(producto.id, color_id)
            if experiencia.asset_url:
                return experiencia.asset_url, experiencia.garment_type, experiencia.body_region
        except (SinRecursoARError, NotFoundError, ValidationError):
            pass
        principal = next((i for i in producto.images if i.is_primary), None)
        if principal:
            return principal.url, None, None
        raise ValidationError("La prenda no tiene foto cargada para generar la imagen.")

    def _active_count(self, user_id: uuid.UUID) -> int:
        return (
            self.db.query(TryOnJobModel)
            .filter(
                TryOnJobModel.user_id == user_id,
                TryOnJobModel.status.in_(ACTIVOS),
            )
            .count()
        )
