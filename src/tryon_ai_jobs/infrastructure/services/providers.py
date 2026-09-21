"""Proveedores de la foto IA realista (plan de evolución, Fase 3).

La generación nunca vive en el request de la API: la petición crea el trabajo y
vuelve al instante; el proveedor se consume cuando el trabajo se procesa.
Además de ser intercambiable (FASHN o un servicio propio con GPU más adelante),
se distinguen tres casos:

  - proveedor real (FASHN): pide clave. Sin clave no promete un resultado: el
    trabajo queda `failed` con una razón clara.
  - proveedor mock: arma una composición local, sin red ni GPU. Sirve para
    ejercitar el flujo completo en desarrollo y en las pruebas.
  - sin proveedor (`none`): el botón existe pero el trabajo explica que falta
    configurar el servicio.
"""
import abc
import base64
from io import BytesIO
import time

import httpx
from PIL import Image

from src.infrastructure.config.settings import settings

# Al ancho de la persona se le pide esta proporción en el mock para no tapar
# las manos: la composición es una simulación, no una prenda puesta.
_MOCK_ANCHO_PRENDA = 0.6
_MOCK_ALTURA_PRENDA = 0.22


class ProveedorError(Exception):
    """El proveedor no pudo generar la imagen."""


class TryOnProvider(abc.ABC):
    nombre: str

    @abc.abstractmethod
    def generar(
        self, persona: bytes, prenda: bytes, prenda_tipo: str | None
    ) -> bytes:
        """Devuelve los bytes de la imagen generada o lanza ProveedorError."""


class ProveedorVacio(TryOnProvider):
    """Sin proveedor configurado: el resultado es una explicación, no una foto."""

    nombre = "none"

    def generar(self, persona: bytes, prenda: bytes, prenda_tipo: str | None) -> bytes:
        raise ProveedorError(
            "No hay proveedor de foto IA configurado (TRYON_PROVIDER/TRYON_API_KEY). "
            "La foto realista no se puede generar todavía."
        )


class ProveedorMock(TryOnProvider):
    """Composición local: monta la prenda sobre la persona a modo de simulacro.

    Es deliberadamente simple (sin deformación de tela ni luz): existe para que
    el flujo de trabajos, límites y expiración se prueben sin depender de un
    servicio externo. El resultado se marca siempre como simulación.
    """

    nombre = "mock"

    def generar(self, persona: bytes, prenda: bytes, prenda_tipo: str | None) -> bytes:
        with Image.open(BytesIO(persona)) as im_persona:
            im_persona.load()
            persona_img = im_persona.convert("RGBA")
        with Image.open(BytesIO(prenda)) as im_prenda:
            im_prenda.load()
            prenda_img = im_prenda.convert("RGBA")

        ancho_persona, alto_persona = persona_img.size
        ancho_prenda = max(10, int(ancho_persona * _MOCK_ANCHO_PRENDA))
        # Conserva la proporción de la prenda para que la composición respete
        # la silueta (un vestido es más alto que ancho, un short no tanto).
        proporcion = prenda_img.size[1] / max(1, prenda_img.size[0])
        alto_prenda = int(ancho_prenda * proporcion)
        prenda_img = prenda_img.resize((ancho_prenda, alto_prenda), Image.LANCZOS)

        lienzo = persona_img.copy()
        x = (ancho_persona - ancho_prenda) // 2
        y = int(alto_persona * _MOCK_ALTURA_PRENDA)
        lienzo.alpha_composite(prenda_img, (x, y))
        salida = BytesIO()
        lienzo.save(salida, "WEBP", quality=88, method=4)
        return salida.getvalue()


class ProveedorFashn(TryOnProvider):
    """FASHN: servicio de virtual try-on.

    El proveedor es intercambiable y este es el punto de conexión real: requiere
    la clave en el entorno y, al procesarse el trabajo, llamaría a la API de
    FASHN con la foto de la persona y la prenda. La integración exacta (modelo,
    subida de imágenes, webhook de resultado) depende de la cuenta y se evalúa
    antes de activarla, como pide el plan: costo por imagen, tiempos y política
    de eliminación. Hasta entonces el trabajo falla con una razón clara en vez
    de inventar un resultado.
    """

    nombre = "fashn"

    def __init__(self) -> None:
        if not settings.tryon_api_key:
            raise ProveedorError(
                "TRYON_API_KEY no está configurada. Sumá la clave de FASHN para "
                "generar la foto realista."
            )

    @staticmethod
    def _data_uri(datos: bytes) -> str:
        """FASHN admite data URI. Así la foto privada nunca necesita exponerse
        públicamente y el proveedor puede procesar también el storage local."""
        try:
            with Image.open(BytesIO(datos)) as imagen:
                formato = (imagen.format or "PNG").lower()
        except Exception as error:  # noqa: BLE001 - se convierte en error visible del trabajo
            raise ProveedorError("La imagen enviada no tiene un formato válido.") from error
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(
            formato, "png"
        )
        return f"data:image/{mime};base64," + base64.b64encode(datos).decode("ascii")

    @staticmethod
    def _categoria(tipo: str | None) -> str:
        texto = (tipo or "").lower()
        if any(palabra in texto for palabra in ("vestido", "enterizo", "jumpsuit")):
            return "one-pieces"
        if any(palabra in texto for palabra in ("pantal", "jean", "short", "falda", "legging")):
            return "bottoms"
        return "tops" if texto else "auto"

    @staticmethod
    def _detalle_error(error: object) -> str:
        if isinstance(error, dict):
            return str(error.get("message") or error.get("name") or "FASHN no pudo generar la imagen.")
        return str(error or "FASHN no pudo generar la imagen.")

    def generar(self, persona: bytes, prenda: bytes, prenda_tipo: str | None) -> bytes:
        """Envía las imágenes a FASHN y espera únicamente este trabajo.

        La API devuelve un identificador y su estado se consulta en `/v1/status`.
        Este método se ejecuta desde la consulta del trabajo propio del cliente;
        por eso el trabajo ya existe, puede fallar de forma trazable y queda
        cubierto por el límite de trabajos activos.
        """
        headers = {"Authorization": f"Bearer {settings.tryon_api_key}"}
        cuerpo = {
            "model_name": "tryon-v1.6",
            "inputs": {
                "model_image": self._data_uri(persona),
                "garment_image": self._data_uri(prenda),
                "category": self._categoria(prenda_tipo),
                "mode": "balanced",
                "num_samples": 1,
                "output_format": "jpeg",
                "moderation_level": "conservative",
            },
        }
        try:
            inicio = httpx.post(
                "https://api.fashn.ai/v1/run", headers=headers, json=cuerpo, timeout=30
            )
            inicio.raise_for_status()
            prediccion = inicio.json()
            prediction_id = prediccion.get("id")
            if not prediction_id:
                raise ProveedorError(self._detalle_error(prediccion.get("error")))

            # El modo balanced suele finalizar en segundos. Se limita el tiempo
            # para que un proveedor lento no deje una petición web indefinida.
            limite = time.monotonic() + 75
            while time.monotonic() < limite:
                estado = httpx.get(
                    f"https://api.fashn.ai/v1/status/{prediction_id}",
                    headers=headers,
                    timeout=20,
                )
                estado.raise_for_status()
                datos = estado.json()
                if datos.get("status") == "completed":
                    salidas = datos.get("output") or []
                    if not salidas:
                        raise ProveedorError("FASHN terminó sin entregar una imagen.")
                    imagen = httpx.get(str(salidas[0]), timeout=30)
                    imagen.raise_for_status()
                    return imagen.content
                if datos.get("status") == "failed":
                    raise ProveedorError(self._detalle_error(datos.get("error")))
                time.sleep(2)
        except httpx.HTTPError as error:
            raise ProveedorError("No se pudo comunicar con el proveedor de foto IA.") from error
        raise ProveedorError("La foto IA tardó demasiado. Intentá nuevamente.")


def resolver_proveedor(nombre: str | None = None) -> TryOnProvider:
    """Devuelve el proveedor registrado en el trabajo.

    Guardar la elección evita que una foto pendiente cambie de proveedor si la
    configuración del servidor se modifica antes de su siguiente consulta.
    """
    proveedor = nombre or settings.tryon_provider
    if proveedor == "fashn":
        return ProveedorFashn()
    if proveedor == "mock":
        return ProveedorMock()
    return ProveedorVacio()
