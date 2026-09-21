"""Procesamiento de un trabajo de foto IA.

Pasa el trabajo de `queued` a `processing` y, al terminar, a `ready` con la URL
del resultado o a `failed` con la razón. Corre cuando se consulta el estado:
así no hace falta worker ni cola para que el flujo sea utilizable, y la petición
que crea el trabajo vuelve al instante (no bloquea la cámara ni el botón).
"""
from pathlib import Path

from sqlalchemy.orm import Session

from src.infrastructure.config.settings import settings
from src.tryon_ai_jobs.domain import ACTIVOS, ESTADO_FALLIDO, ESTADO_LISTO, ESTADO_PROCESANDO
from src.tryon_ai_jobs.infrastructure.persistence.models.tryon_job import TryOnJobModel
from src.tryon_ai_jobs.infrastructure.services import archivos
from src.tryon_ai_jobs.infrastructure.services.providers import ProveedorError, resolver_proveedor
from src.usuarios_catalogo.infrastructure.media_storage import store_image


def procesar_trabajo(db: Session, trabajo: TryOnJobModel) -> None:
    """Genera la imagen con el proveedor configurado. Idempotente por estado."""
    if trabajo.status not in ACTIVOS:
        return
    trabajo.status = ESTADO_PROCESANDO
    db.flush()
    try:
        proveedor = resolver_proveedor(trabajo.provider)
        persona = archivos.descargar(trabajo.person_photo_url)
        prenda = archivos.descargar(trabajo.garment_image_url)
        resultado = proveedor.generar(persona, prenda, trabajo.garment_type)
        nombre, _, _ = store_image(resultado, Path(settings.media_storage_dir).resolve())
        trabajo.result_url = f"{settings.media_public_base_url.rstrip('/')}/{nombre}"
        trabajo.status = ESTADO_LISTO
        trabajo.error = None
    except ProveedorError as error:
        trabajo.status = ESTADO_FALLIDO
        trabajo.error = str(error)[:500]
    except Exception as error:  # noqa: BLE001 - cualquier fallo deja rastro visible
        trabajo.status = ESTADO_FALLIDO
        trabajo.error = f"Error inesperado: {str(error)[:400]}"
    db.commit()
    db.refresh(trabajo)
