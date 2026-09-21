"""Fase 3 del plan de evolución: trabajos de foto IA realista (try-on).

Un cliente pide una foto realista de la prenda sobre su propia foto. El trabajo
se crea al instante (`queued`), la generación corre cuando se consulta (con el
proveedor mock en tests, sin red), y la privacidad es parte del contrato:
cancelar, expirar o eliminar borra la foto de la persona del disco.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.base import Base
from src.infrastructure.database.session import get_db
from src.main import create_app
from src.shared.exceptions.domain_exception import NotFoundError
from src.tryon_ai_jobs.infrastructure.persistence.models.tryon_job import TryOnJobModel


def foto_persona(ancho=200, alto=400) -> bytes:
    dibujo, lienzo = _imagen(ancho, alto)
    dibujo.ellipse([70, 20, 130, 95], fill=(120, 90, 70))  # cabeza
    dibujo.polygon(
        [(20, 100), (85, 140), (115, 140), (180, 100), (180, 220), (20, 220)],
        fill=(60, 70, 130),
    )  # torso y brazos
    return _bytes(lienzo)


def foto_prenda(ancho=160, alto=200) -> bytes:
    dibujo, lienzo = _imagen(ancho, alto)
    dibujo.polygon([(30, 10), (80, 5), (130, 10), (130, 190), (30, 190)], fill=(200, 60, 70))
    return _bytes(lienzo)


def _imagen(ancho, alto, fondo=(255, 255, 255)):
    lienzo = Image.new("RGB", (ancho, alto), fondo)
    return ImageDraw.Draw(lienzo), lienzo


def _bytes(lienzo: Image.Image) -> bytes:
    salida = BytesIO()
    lienzo.save(salida, "PNG")
    return salida.getvalue()


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    from sqlalchemy import create_engine

    monkeypatch.setattr(
        "src.infrastructure.config.settings.settings.media_storage_dir", str(tmp_path), raising=False
    )
    monkeypatch.setattr(
        "src.infrastructure.config.settings.settings.media_public_base_url",
        "http://test/media",
        raising=False,
    )
    monkeypatch.setattr(
        "src.infrastructure.config.settings.settings.tryon_provider", "mock", raising=False
    )
    monkeypatch.setattr(
        "src.infrastructure.config.settings.settings.tryon_max_active_jobs", 3, raising=False
    )
    monkeypatch.setattr(
        "src.infrastructure.config.settings.settings.ai_api_key", "", raising=False
    )

    engine = create_engine(
        "sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    from src.auth.infrastructure.persistence.models.user import UserModel
    from src.usuarios_catalogo.infrastructure.models.catalog import (
        CategoryModel,
        ColorModel,
        ProductImageModel,
        ProductModel,
        ProductVariantModel,
        SizeModel,
    )

    with Session(engine, expire_on_commit=False) as db:
        cliente = UserModel(
            email="cliente@example.test", password_hash="unused", first_name="Clara",
            last_name="Cliente", is_active=True, is_verified=True,
        )
        otro = UserModel(
            email="otro@example.test", password_hash="unused", first_name="Otro",
            last_name="Usuario", is_active=True, is_verified=True,
        )
        categoria = CategoryModel(name="Remeras", slug="remeras")
        color = ColorModel(name="Rojo tinto", hex_code="#C0392B")
        talla = SizeModel(code="M", name="Mediana")
        db.add_all([cliente, otro, categoria, color, talla])
        db.flush()

        archivo = tmp_path / "pantalon.png"
        archivo.write_bytes(foto_prenda())
        producto = ProductModel(
            name="Remera clásica", slug="remera-clasica", description="prueba",
            base_price=Decimal("149"), category_id=categoria.id,
        )
        producto.images = [ProductImageModel(url=f"http://test/media/{archivo.name}", is_primary=True)]
        producto.variants.append(
            ProductVariantModel(
                color_id=color.id, size_id=talla.id, sku="SKU-REMERA-1", is_active=True
            )
        )
        db.add(producto)
        db.commit()

        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: cliente
        with TestClient(app) as client:
            yield client, db, cliente, otro, producto, color, tmp_path
    engine.dispose()


def pedir_foto(client, producto, color, consentimiento=True, **kwargs):
    return client.post(
        "/api/v1/tryon-ai/jobs",
        files={"file": ("persona.png", foto_persona(), "image/png")},
        data={
            "product_id": str(producto.id),
            "color_id": str(color.id),
            "privacy_consent": str(consentimiento).lower(),
            **kwargs,
        },
    )


def test_sin_consentimiento_no_se_procesa_la_foto(mundo):
    client, *_ = mundo
    respuesta = pedir_foto(client, mundo[4], mundo[5], consentimiento=False)
    assert respuesta.status_code == 422, respuesta.text
    assert respuesta.json()["error"]["code"] == "validation_error"


def test_crear_devuelve_encuesto_sin_esperar_la_generacion(mundo):
    client, *_ = mundo
    creado = pedir_foto(client, mundo[4], mundo[5])
    assert creado.status_code == 200, creado.text
    datos = creado.json()["data"]
    assert datos["status"] == "queued"
    assert datos["provider"] == "mock"
    assert datos["result_url"] is None
    assert datos["is_simulation"] is True
    assert "simulación" in datos["disclaimer"].lower()


def test_consultar_dispara_la_generacion_mock(mundo):
    client, *_ = mundo
    trabajo = pedir_foto(client, mundo[4], mundo[5]).json()["data"]
    resultado = client.get(f"/api/v1/tryon-ai/jobs/{trabajo['id']}")
    assert resultado.status_code == 200, resultado.text
    datos = resultado.json()["data"]
    assert datos["status"] == "ready"
    assert datos["result_url"].startswith("http://test/media/")
    assert datos["error"] is None
    assert datos["expires_at"]


def test_proveedor_no_configurado_falla_con_razon_visible(mundo, monkeypatch):
    monkeypatch.setattr(
        "src.infrastructure.config.settings.settings.tryon_provider", "none", raising=False
    )
    client, *_ = mundo
    trabajo = pedir_foto(client, mundo[4], mundo[5]).json()["data"]
    resultado = client.get(f"/api/v1/tryon-ai/jobs/{trabajo['id']}")
    datos = resultado.json()["data"]
    assert datos["status"] == "failed"
    assert "No hay proveedor" in datos["error"]


def test_el_limite_de_trabajos_activos_se_respeta(mundo, monkeypatch):
    from src.infrastructure.config.settings import settings

    monkeypatch.setattr(settings, "tryon_max_active_jobs", 1)
    client, *_ = mundo
    primero = pedir_foto(client, mundo[4], mundo[5])
    assert primero.status_code == 200, primero.text
    segundo = pedir_foto(client, mundo[4], mundo[5])
    assert segundo.status_code == 422, segundo.text
    assert "en curso" in segundo.json()["error"]["message"]


def test_expirar_borra_la_foto_y_el_resultado_del_disco(mundo):
    client, db, *_ = mundo
    trabajo = pedir_foto(client, mundo[4], mundo[5]).json()["data"]
    client.get(f"/api/v1/tryon-ai/jobs/{trabajo['id']}")  # queda ready

    fila = db.get(TryOnJobModel, uuid.UUID(trabajo["id"]))
    fila.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()

    resultado = client.get(f"/api/v1/tryon-ai/jobs/{trabajo['id']}")
    assert resultado.status_code == 200, resultado.text
    datos = resultado.json()["data"]
    assert datos["status"] == "expired"
    assert "expiró" in datos["error"]

    directorio = Path(mundo[6])
    nombre_persona = Path(fila.person_photo_url.split("/")[-1])
    nombre_resultado = Path(fila.result_url.split("/")[-1])
    assert not (directorio / nombre_persona).exists()
    assert not (directorio / nombre_resultado).exists()


def test_cancelar_borra_la_foto_de_la_persona(mundo):
    client, db, *_ = mundo
    trabajo = pedir_foto(client, mundo[4], mundo[5]).json()["data"]
    fila = db.get(TryOnJobModel, uuid.UUID(trabajo["id"]))
    nombre_persona = Path(fila.person_photo_url.split("/")[-1])
    assert (Path(mundo[6]) / nombre_persona).exists()

    cancelado = client.patch(f"/api/v1/tryon-ai/jobs/{trabajo['id']}/cancel")
    assert cancelado.status_code == 200, cancelado.text
    assert cancelado.json()["data"]["status"] == "cancelled"
    assert not (Path(mundo[6]) / nombre_persona).exists()


def test_cancelar_un_trabajo_terminado_no_se_puede(mundo):
    client, *_ = mundo
    trabajo = pedir_foto(client, mundo[4], mundo[5]).json()["data"]
    client.get(f"/api/v1/tryon-ai/jobs/{trabajo['id']}")  # ready
    cancelado = client.patch(f"/api/v1/tryon-ai/jobs/{trabajo['id']}/cancel")
    assert cancelado.status_code == 422, cancelado.text


def test_eliminar_saca_el_trabajo_del_historial(mundo):
    client, *_ = mundo
    trabajo = pedir_foto(client, mundo[4], mundo[5]).json()["data"]
    assert client.get("/api/v1/tryon-ai/jobs").json()["data"]

    borrado = client.delete(f"/api/v1/tryon-ai/jobs/{trabajo['id']}")
    assert borrado.status_code == 204
    assert client.get("/api/v1/tryon-ai/jobs").json()["data"] == []


def test_ningun_otro_usuario_puede_acceder_al_trabajo(mundo):
    client, db, _, otro, *_ = mundo
    trabajo = pedir_foto(client, mundo[4], mundo[5]).json()["data"]
    ajeno = db.get(TryOnJobModel, uuid.UUID(trabajo["id"]))
    from src.tryon_ai_jobs.application.use_cases.gestionar_trabajos import CancelarTrabajo
    from src.tryon_ai_jobs.application.use_cases.consultar_trabajo import ConsultarTrabajo

    with pytest.raises(NotFoundError):
        ConsultarTrabajo(db).execute(otro, ajeno.id)
    with pytest.raises(NotFoundError):
        CancelarTrabajo(db).execute(otro, ajeno.id)


def test_proveedor_fashn_envia_las_imagenes_y_descarga_el_resultado(monkeypatch):
    """La integración real no depende de URLs públicas: manda data URI y
    guarda localmente el resultado descargado del CDN."""
    from src.infrastructure.config.settings import settings
    from src.tryon_ai_jobs.infrastructure.services import providers

    monkeypatch.setattr(settings, "tryon_api_key", "key-de-prueba", raising=False)
    monkeypatch.setattr(providers.time, "sleep", lambda _: None)
    generado = foto_persona(80, 120)
    llamadas: list[tuple[str, object]] = []

    class Respuesta:
        def __init__(self, datos=None, contenido=b""):
            self._datos = datos or {}
            self.content = contenido

        def raise_for_status(self):
            return None

        def json(self):
            return self._datos

    def post(url, **kwargs):
        llamadas.append((url, kwargs["json"]))
        return Respuesta({"id": "prediccion-1", "error": None})

    def get(url, **kwargs):
        llamadas.append((url, None))
        if "/v1/status/" in url:
            return Respuesta({"status": "completed", "output": ["https://cdn.example/out.jpg"]})
        return Respuesta(contenido=generado)

    monkeypatch.setattr(providers.httpx, "post", post)
    monkeypatch.setattr(providers.httpx, "get", get)

    resultado = providers.ProveedorFashn().generar(foto_persona(), foto_prenda(), "camiseta")

    assert resultado == generado
    solicitud = llamadas[0][1]
    assert solicitud["model_name"] == "tryon-v1.6"
    assert solicitud["inputs"]["category"] == "tops"
    assert solicitud["inputs"]["model_image"].startswith("data:image/png;base64,")
    assert any("/v1/status/prediccion-1" in url for url, _ in llamadas)
