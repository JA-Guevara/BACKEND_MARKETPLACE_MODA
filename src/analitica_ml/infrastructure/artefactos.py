import gzip
import hashlib
import io
from typing import Any

import joblib

from src.shared.exceptions.domain_exception import ValidationError


MAX_ARTIFACT_BYTES = 5 * 1024 * 1024


class ArtefactoDemasiadoGrande(ValidationError):
    """El artefacto comprimido supera el límite que acepta la base."""

    code = "ml_artifact_too_large"

    def __init__(self, size: int, limit: int) -> None:
        super().__init__(
            f"El artefacto de Machine Learning ocupa {size} bytes y supera el límite de {limit} bytes."
        )


class GestorArtefactosML:
    """Serializa modelos en memoria; el artefacto se guarda en la base.

    Railway borra el sistema de archivos en cada despliegue, así que ningún
    modelo entrenado puede depender de un archivo local. La fila de
    ``ml_models`` conserva el binario comprimido, su tamaño y su hash.
    """

    def __init__(self, max_bytes: int = MAX_ARTIFACT_BYTES) -> None:
        self.max_bytes = max_bytes

    def serializar(self, obj: Any) -> bytes:
        buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=buffer, mode="wb") as gz:
            joblib.dump(obj, gz)
        data = buffer.getvalue()
        if len(data) > self.max_bytes:
            raise ArtefactoDemasiadoGrande(len(data), self.max_bytes)
        return data

    def deserializar(self, data: bytes) -> Any:
        if not data:
            raise ValidationError("El artefacto de Machine Learning está vacío.")
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as gz:
            return joblib.load(gz)

    @staticmethod
    def sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()
