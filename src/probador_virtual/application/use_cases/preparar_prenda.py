"""Preparación del recurso del probador a partir de la foto del producto.

Ocurre una sola vez, cuando el administrador lo pide: separa la prenda del
fondo, determina qué parte del cuerpo cubre y calcula sus puntos de anclaje. El
probador del cliente no vuelve a llamar a ningún modelo pesado; solo consume
este recurso ya preparado.

Reparto de responsabilidades, para no atribuirle a la IA más de lo que hace:
  - Clasificación (tipo de prenda y región corporal): modelo de visión cuando
    hay clave configurada; si no, deducción por categoría y nombre.
  - Segmentación (quitar el fondo): algoritmo sobre la imagen, sin modelo.
  - Anclajes: geometría sobre la máscara resultante.
"""
import json
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.infrastructure.config.settings import settings
from src.probador_virtual.infrastructure.persistence.models.recurso_tryon import (
    ESTADO_FALLIDO,
    ESTADO_LISTO,
    MODO_2_5D,
    TryOnAssetModel,
)
from src.probador_virtual.infrastructure.services import anclajes, segmentacion
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError
from src.usuarios_catalogo.infrastructure.media_storage import store_image
from src.usuarios_catalogo.infrastructure.models.catalog import ColorModel, ProductModel

TIPOS = [
    "camiseta", "polo", "camisa", "blusa", "chaqueta", "abrigo", "vestido",
    "pantalon", "short", "falda", "calzado", "accesorio",
]


class PrepararPrenda:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------------------------------------------------------------- lectura
    def _producto(self, product_id: uuid.UUID) -> ProductModel:
        producto = self.db.get(ProductModel, product_id)
        if not producto or producto.deleted_at:
            raise NotFoundError("Prenda no encontrada.")
        return producto

    def _color(self, color_id: uuid.UUID) -> ColorModel:
        color = self.db.get(ColorModel, color_id)
        if not color:
            raise NotFoundError("Color no encontrado.")
        return color

    def _imagen_fuente(self, producto: ProductModel, color: ColorModel) -> str:
        """La foto comercial del producto es la fuente del recurso."""
        if not producto.images:
            raise ValidationError(
                "La prenda no tiene imagen cargada. Subí la foto del producto antes de preparar el probador."
            )
        principal = next((i for i in producto.images if i.is_primary), producto.images[0])
        return principal.url

    def _descargar(self, url: str) -> bytes:
        """Lee la imagen, sea un archivo servido por la aplicación o una URL."""
        ruta = urlparse(url).path
        nombre = Path(ruta).name
        local = Path(settings.media_storage_dir).resolve() / nombre
        if local.is_file():
            return local.read_bytes()
        if not url.lower().startswith(("http://", "https://")):
            # Ruta relativa servida por el frontend (por ejemplo /demo/x.webp).
            publico = Path(settings.media_storage_dir).resolve().parent.parent
            candidato = publico / ruta.lstrip("/")
            if candidato.is_file():
                return candidato.read_bytes()
            raise ValidationError("No se pudo leer la imagen de la prenda.")
        try:
            respuesta = httpx.get(url, timeout=20, follow_redirects=True)
            respuesta.raise_for_status()
            return respuesta.content
        except httpx.HTTPError as error:
            raise ValidationError("No se pudo descargar la imagen de la prenda.") from error

    # ------------------------------------------------------------ clasificación
    def _clasificar(self, producto: ProductModel) -> tuple[str | None, str, dict]:
        """Tipo de prenda y región corporal. Usa el modelo de visión si hay
        clave; si no, deduce por categoría y nombre, que para un catálogo de
        ropa acierta en la mayoría de los casos."""
        referencia = f"{producto.name} {producto.category.name if producto.category else ''}"
        respaldo = anclajes.region_por_defecto(referencia)
        if not settings.ai_api_key:
            return None, respaldo, {"source": "heuristica", "reference": referencia.strip()}
        try:
            respuesta = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": "Bearer " + settings.ai_api_key},
                json={
                    "model": settings.ai_model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Clasificás prendas para un probador virtual. Respondé JSON con "
                                "garment_type (uno de: " + ", ".join(TIPOS) + ") y body_region "
                                "(uno de: upper_body, lower_body, full_body, feet)."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Prenda: {producto.name}. Categoría: "
                            f"{producto.category.name if producto.category else 'sin categoría'}. "
                            f"Descripción: {(producto.description or '')[:300]}",
                        },
                    ],
                },
                timeout=25,
            )
            respuesta.raise_for_status()
            contenido = json.loads(respuesta.json()["choices"][0]["message"]["content"])
            region = str(contenido.get("body_region") or "").strip()
            tipo = str(contenido.get("garment_type") or "").strip() or None
            if region not in anclajes.REGIONES:
                region = respaldo
            return tipo, region, {"source": "modelo", "model": settings.ai_model, "raw": contenido}
        except Exception as error:  # noqa: BLE001 - el respaldo debe cubrir cualquier fallo
            return None, respaldo, {"source": "heuristica", "fallback_reason": str(error)[:200]}

    # --------------------------------------------------------------- ejecución
    def execute(
        self, product_id: uuid.UUID, color_id: uuid.UUID, actor: UserModel
    ) -> TryOnAssetModel:
        producto = self._producto(product_id)
        color = self._color(color_id)
        fuente = self._imagen_fuente(producto, color)

        recurso = (
            self.db.query(TryOnAssetModel)
            .filter(TryOnAssetModel.product_id == product_id, TryOnAssetModel.color_id == color_id)
            .first()
        )
        if recurso is None:
            recurso = TryOnAssetModel(product_id=product_id, color_id=color_id, source_image_url=fuente)
            self.db.add(recurso)
        recurso.source_image_url = fuente
        recurso.mode = MODO_2_5D

        try:
            datos = self._descargar(fuente)
            recorte = segmentacion.recortar_fondo(datos)
            tipo, region, metadatos = self._clasificar(producto)
            directorio = Path(settings.media_storage_dir).resolve()
            nombre_prenda, ancho, alto = store_image(segmentacion.a_webp(recorte.imagen), directorio)
            nombre_mascara, _, _ = store_image(segmentacion.a_png_mascara(recorte.mascara), directorio)
            base = settings.media_public_base_url.rstrip("/")

            recurso.transparent_url = f"{base}/{nombre_prenda}"
            recurso.mask_url = f"{base}/{nombre_mascara}"
            recurso.garment_type = tipo
            recurso.body_region = region
            recurso.anchor_points = anclajes.calcular_anclajes(recorte.mascara, region)
            recurso.ai_status = ESTADO_LISTO
            recurso.ai_error = None
            recurso.ai_metadata = {
                **metadatos,
                "coverage": round(recorte.cobertura, 4),
                "output": {"width": ancho, "height": alto},
                "segmentation": "pillow_floodfill",
            }
            mensaje = "Recurso de probador preparado desde la foto del producto."
        except ValidationError:
            raise
        except Exception as error:  # noqa: BLE001 - se registra y queda visible en el panel
            recurso.ai_status = ESTADO_FALLIDO
            recurso.ai_error = str(error)[:500]
            mensaje = "Fallo la preparacion del recurso de probador."

        self.db.flush()
        RecordAuditEvent(self.db).execute(
            action="vestidor.asset_prepared",
            entity_type="tryon_asset",
            entity_id=str(recurso.id),
            description=mensaje,
            actor_user_id=actor.id,
            metadata={
                "product_id": str(product_id),
                "color_id": str(color_id),
                "status": recurso.ai_status,
                "body_region": recurso.body_region,
            },
        )
        self.db.commit()
        self.db.refresh(recurso)
        return recurso
