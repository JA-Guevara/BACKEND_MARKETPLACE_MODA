"""Lectura y borrado de imágenes del trey-on.

La foto de la persona y el resultado viven en el storage local del proyecto y
se publican por su URL pública; este módulo sabe resolver esa URL de vuelta al
archivo en disco para leerlo o borrarlo. El borrado es de verdad: no se retiene
la foto de la persona más de lo necesario.
"""
from pathlib import Path
from urllib.parse import urlparse

import httpx

from src.infrastructure.config.settings import settings


def descargar(url: str) -> bytes:
    """Lee la imagen, sea un archivo en disco o una URL remota."""
    ruta = urlparse(url).path
    local = Path(settings.media_storage_dir).resolve() / Path(ruta).name
    if local.is_file():
        return local.read_bytes()
    try:
        respuesta = httpx.get(url, timeout=20, follow_redirects=True)
        respuesta.raise_for_status()
        return respuesta.content
    except httpx.HTTPError as error:
        raise ValueError("No se pudo descargar la imagen.") from error


def borrar_archivo(url: str | None) -> None:
    """Elimina el archivo detrás de una URL pública si existe. Llamar con la URL
    de la foto de la persona (o del resultado) garantiza que no quede retenida."""
    if not url:
        return
    nombre = Path(urlparse(url).path).name
    ruta = Path(settings.media_storage_dir).resolve() / nombre
    if ruta.is_file():
        try:
            ruta.unlink()
        except OSError:
            pass  # el archivo puede haber expirado entre dos lecturas