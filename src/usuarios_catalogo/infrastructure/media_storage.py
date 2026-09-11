"""Validated product images. Re-encoding removes EXIF and untrusted metadata."""
from io import BytesIO
from pathlib import Path
from uuid import uuid4
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from src.shared.exceptions.domain_exception import ValidationError

MAX_PIXELS = 24_000_000

def store_image(raw: bytes, directory: Path) -> tuple[str, int, int]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as source:
                if source.format not in {'JPEG', 'PNG', 'WEBP'}:
                    raise ValidationError('Solo se admiten imágenes JPEG, PNG o WebP.')
                if source.width * source.height > MAX_PIXELS:
                    raise ValidationError('La imagen excede 24 megapíxeles.')
                source.load()
                picture = ImageOps.exif_transpose(source).convert('RGBA' if 'A' in source.getbands() else 'RGB')
                picture.thumbnail((2400, 2400))
                directory.mkdir(parents=True, exist_ok=True)
                name = uuid4().hex + '.webp'
                picture.save(directory / name, 'WEBP', quality=88, method=4)
                return name, picture.width, picture.height
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValidationError('El archivo no es una imagen válida o segura.') from exc
