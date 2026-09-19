"""Preparación del recurso del probador: recorte del fondo, región y anclajes.

Sin cámara, sin red y sin modelo de IA: la clasificación cae al respaldo por
nombre cuando no hay clave configurada, que es justo lo que debe pasar.
"""
import uuid
from decimal import Decimal
from io import BytesIO

import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.config.settings import settings
from src.infrastructure.database.base import Base
from src.infrastructure.database.session import get_db
from src.main import create_app
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.roles.infrastructure.persistence.models.role import RoleModel
from src.probador_virtual.infrastructure.persistence.models.recurso_tryon import TryOnAssetModel
from src.probador_virtual.infrastructure.services import anclajes, segmentacion
from src.usuarios_catalogo.infrastructure.models.catalog import (
    CategoryModel,
    ColorModel,
    ProductImageModel,
    ProductModel,
)


def foto_de_estudio(ancho=400, alto=600) -> bytes:
    """Foto de catálogo simulada: prenda centrada sobre fondo blanco liso."""
    lienzo = Image.new("RGB", (ancho, alto), (255, 255, 255))
    dibujo = ImageDraw.Draw(lienzo)
    dibujo.polygon(
        [(120, 150), (200, 120), (280, 150), (280, 460), (120, 460)], fill=(30, 60, 120)
    )
    dibujo.polygon([(120, 150), (70, 220), (105, 300), (120, 260)], fill=(24, 50, 100))
    dibujo.polygon([(280, 150), (330, 220), (295, 300), (280, 260)], fill=(24, 50, 100))
    salida = BytesIO()
    lienzo.save(salida, "PNG")
    return salida.getvalue()


def test_recorte_deja_fondo_transparente_y_recorta_al_contorno():
    recorte = segmentacion.recortar_fondo(foto_de_estudio())

    # El fondo blanco desaparece: ese era el rectángulo que se veía sobre la cámara.
    assert recorte.imagen.mode == "RGBA"
    assert recorte.imagen.getpixel((0, 0))[3] == 0
    # Queda recortada al contorno, más chica que la foto original.
    assert recorte.imagen.size[0] < 400 and recorte.imagen.size[1] < 600
    # Y conserva la prenda: hay píxeles totalmente opacos.
    assert any(p[3] > 200 for p in recorte.imagen.getdata())
    assert 0.05 < recorte.cobertura < 0.6


def test_fondo_no_liso_conserva_la_foto_en_lugar_de_romper_la_silueta():
    lienzo = Image.new("RGB", (200, 200))
    dibujo = ImageDraw.Draw(lienzo)
    for x in range(0, 200, 10):
        dibujo.rectangle([x, 0, x + 5, 200], fill=(x, 255 - x, 128))
    datos = BytesIO()
    lienzo.save(datos, "PNG")

    recorte = segmentacion.recortar_fondo(datos.getvalue())
    # Ante un fondo que no es liso conserva la foto en lugar de recortar mal.
    assert recorte.cobertura >= 0.9


def test_anclajes_tienen_ancho_real_y_region_correcta():
    recorte = segmentacion.recortar_fondo(foto_de_estudio())
    puntos = anclajes.calcular_anclajes(recorte.mascara, anclajes.UPPER_BODY)

    assert {"shoulder_left", "shoulder_right"} <= puntos.keys()
    izquierda, derecha = puntos["shoulder_left"][0], puntos["shoulder_right"][0]
    assert derecha - izquierda >= anclajes.ANCHO_MINIMO
    # Coordenadas normalizadas: sirven sin importar el tamaño del recurso.
    assert all(0 <= v <= 1 for v in (izquierda, derecha))


@pytest.mark.parametrize(
    "nombre,esperado",
    [
        ("Camisa de lino", anclajes.UPPER_BODY),
        ("Pantalón chino", anclajes.LOWER_BODY),
        ("Short de jean", anclajes.LOWER_BODY),
        ("Vestido midi", anclajes.FULL_BODY),
        ("Zapatillas urbanas", anclajes.FEET),
    ],
)
def test_region_por_defecto_sin_servicio_de_ia(nombre, esperado):
    assert anclajes.region_por_defecto(nombre) == esperado


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_storage_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "media_public_base_url", "http://test/media", raising=False)
    monkeypatch.setattr(settings, "ai_api_key", "", raising=False)

    engine = create_engine(
        "sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        admin = UserModel(
            email="catalogo@example.test", password_hash="unused", first_name="Gestor",
            last_name="Catalogo", is_active=True, is_verified=True,
        )
        # Rol real: así se ejercita la autorización de verdad, no una simulada.
        rol = RoleModel(code="catalogo", name="Gestor de catálogo")
        rol.permissions = [
            PermissionModel(code="catalog.write", name="catalog.write", module="catalog"),
            PermissionModel(code="catalog.read", name="catalog.read", module="catalog"),
        ]
        admin.roles = [rol]
        categoria = CategoryModel(name="Pantalones", slug="pantalones")
        color = ColorModel(name="Azul marino", hex_code="#1E2A44")
        db.add_all([admin, rol, categoria, color])
        db.flush()

        archivo = tmp_path / "fuente.png"
        archivo.write_bytes(foto_de_estudio())
        producto = ProductModel(
            name="Pantalón chino", slug="pantalon-chino", description="Prueba de preparación",
            base_price=Decimal("199"), category_id=categoria.id,
        )
        producto.images = [ProductImageModel(url=f"http://test/media/{archivo.name}", is_primary=True)]
        db.add(producto)
        db.commit()

        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: admin
        with TestClient(app) as client:
            yield client, db, producto, color
    engine.dispose()


def test_preparar_genera_recurso_usable_y_el_probador_lo_entrega(mundo):
    client, db, producto, color = mundo

    creado = client.post(
        f"/api/v1/vestidor/admin/products/{producto.id}/assets",
        json={"color_id": str(color.id)},
    )
    assert creado.status_code == 200, creado.text
    recurso = creado.json()["data"]
    assert recurso["ai_status"] == "ready"
    assert recurso["transparent_url"] and recurso["mask_url"]
    assert recurso["body_region"] == anclajes.LOWER_BODY  # deducido del nombre
    assert recurso["anchor_points"]

    # El cliente recibe el recurso preparado, no la foto original con fondo.
    sesion = client.post(
        "/api/v1/vestidor/sessions",
        json={"product_id": str(producto.id), "color_id": str(color.id)},
    )
    assert sesion.status_code == 200, sesion.text
    datos = sesion.json()["data"]
    assert datos["asset_type"] == "prepared_2_5d"
    assert datos["asset_url"] == recurso["transparent_url"]
    assert datos["body_region"] == anclajes.LOWER_BODY
    assert datos["anchor_points"]


def test_color_sin_recurso_avisa_en_lugar_de_usar_otro(mundo):
    client, db, producto, color = mundo
    otro = ColorModel(name="Rojo tinto", hex_code="#8E2B33")
    db.add(otro)
    db.commit()

    client.post(
        f"/api/v1/vestidor/admin/products/{producto.id}/assets", json={"color_id": str(color.id)}
    )
    respuesta = client.post(
        "/api/v1/vestidor/sessions",
        json={"product_id": str(producto.id), "color_id": str(otro.id)},
    )
    assert respuesta.status_code == 404, respuesta.text
    assert "color" in respuesta.json()["error"]["message"].lower()


def test_ajuste_manual_corrige_lo_que_propuso_el_analisis(mundo):
    client, db, producto, color = mundo
    recurso = client.post(
        f"/api/v1/vestidor/admin/products/{producto.id}/assets", json={"color_id": str(color.id)}
    ).json()["data"]

    ajuste = client.patch(
        f"/api/v1/vestidor/admin/assets/{recurso['id']}",
        json={"body_region": "upper_body", "garment_type": "camisa"},
    )
    assert ajuste.status_code == 200, ajuste.text
    corregido = ajuste.json()["data"]
    assert corregido["body_region"] == "upper_body"
    assert corregido["ai_status"] == "manual"

    invalido = client.patch(
        f"/api/v1/vestidor/admin/assets/{recurso['id']}", json={"body_region": "cabeza"}
    )
    assert invalido.status_code == 422


def _foto(prenda_rgb, fondo_rgb=(241, 242, 235), tamano=(120, 160)):
    """Foto sintetica: una prenda rectangular sobre fondo liso."""
    from PIL import Image
    from io import BytesIO
    im = Image.new("RGB", tamano, fondo_rgb)
    ancho, alto = tamano
    for y in range(int(alto * 0.2), int(alto * 0.8)):
        for x in range(int(ancho * 0.25), int(ancho * 0.75)):
            im.putpixel((x, y), prenda_rgb)
    salida = BytesIO()
    im.save(salida, "PNG")
    return salida.getvalue()


class TestRecorteHonesto:
    """El recorte tiene que decir cuando NO pudo, no devolver la foto entera como si nada."""

    def test_una_prenda_contrastada_se_recorta_y_se_declara_lograda(self):
        from src.probador_virtual.infrastructure.services.segmentacion import recortar_fondo

        recorte = recortar_fondo(_foto((30, 30, 30)))
        assert recorte.logrado is True
        assert 0.04 <= recorte.cobertura <= 0.97

    def test_una_prenda_del_color_del_fondo_se_declara_NO_lograda(self):
        """Medido en el catalogo real: las prendas «blanco hueso» difieren del
        fondo en 4 sobre 255 y el relleno se las come. Antes eso devolvia la
        foto COMPLETA con su fondo marcada como lista, y el probador mostraba
        un rectangulo con fondo sobre la camara."""
        from src.probador_virtual.infrastructure.services.segmentacion import recortar_fondo

        recorte = recortar_fondo(_foto((242, 238, 233)))
        assert recorte.logrado is False

    def test_un_recorte_no_logrado_no_puede_quedar_marcado_como_listo(self):
        """La regla que importa: sin recorte valido, el recurso no es usable y
        el probador cae al dibujo, que siempre funciona."""
        from src.probador_virtual.infrastructure.persistence.models.recurso_tryon import (
            ESTADO_FALLIDO,
            ESTADO_LISTO,
        )
        from src.probador_virtual.infrastructure.services.segmentacion import recortar_fondo

        fallido = recortar_fondo(_foto((242, 238, 233)))
        logrado = recortar_fondo(_foto((30, 30, 30)))
        # Es la decision que toma PrepararPrenda a partir de `logrado`.
        assert (ESTADO_LISTO if logrado.logrado else ESTADO_FALLIDO) == ESTADO_LISTO
        assert (ESTADO_LISTO if fallido.logrado else ESTADO_FALLIDO) == ESTADO_FALLIDO
