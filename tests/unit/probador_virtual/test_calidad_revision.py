"""Fase 1 del plan de evolución: calidad del recurso y su revisión.

Un recorte dudoso no se publica solo: queda en `review` y el probador cae al
dibujo hasta que el administrador lo aprueba o lo descarta. Acá se ejercita el
puntaje de calidad, la revisión, el reintento y la preparación masiva.
"""
from decimal import Decimal
from io import BytesIO

from PIL import Image, ImageDraw
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.base import Base
from src.infrastructure.database.session import get_db
from src.main import create_app
from src.probador_virtual.infrastructure.services import anclajes, calidad, segmentacion


def _imagen(ancho, alto, fondo=(255, 255, 255)):
    lienzo = Image.new("RGB", (ancho, alto), fondo)
    return ImageDraw.Draw(lienzo), lienzo


def _bytes(lienzo: Image.Image) -> bytes:
    salida = BytesIO()
    lienzo.save(salida, "PNG")
    return salida.getvalue()


def foto_de_estudio(ancho=400, alto=600) -> bytes:
    """Prenda contrastada y centrada sobre fondo liso: recorte claro."""
    dibujo, lienzo = _imagen(ancho, alto)
    dibujo.polygon(
        [(120, 150), (200, 120), (280, 150), (280, 460), (120, 460)], fill=(30, 60, 120)
    )
    dibujo.polygon([(120, 150), (70, 220), (105, 300), (120, 260)], fill=(24, 50, 100))
    dibujo.polygon([(280, 150), (330, 220), (295, 300), (280, 260)], fill=(24, 50, 100))
    return _bytes(lienzo)


def foto_dudosa(ancho=400, alto=600) -> bytes:
    """Una tira tan fina y alta que la silueta es atípica: recorte logrado pero
    de calidad dudosa, justo lo que tiene que ir a revisión."""
    dibujo, lienzo = _imagen(ancho, alto)
    dibujo.rectangle([185, 50, 215, 550], fill=(30, 60, 120))
    return _bytes(lienzo)


def foto_sin_fondo_liso(ancho=200, alto=200) -> bytes:
    dibujo, lienzo = _imagen(ancho, alto)
    for x in range(0, ancho, 10):
        dibujo.rectangle([x, 0, x + 5, alto], fill=(x, 255 - x, 128))
    return _bytes(lienzo)


# ------------------------------------------------------------------ puntaje ---


def test_prenda_clara_queda_con_puntaje_de_publicar():
    recorte = segmentacion.recortar_fondo(foto_de_estudio())
    puntaje, razon = calidad.puntuar(recorte.mascara, recorte.cobertura, anclajes.UPPER_BODY)
    assert puntaje >= calidad.UMBRAL_PUBLICAR
    assert razon == calidad.RAZON_BUENA


def test_tira_atipica_queda_debajo_del_umbral():
    recorte = segmentacion.recortar_fondo(foto_dudosa())
    puntaje, razon = calidad.puntuar(recorte.mascara, recorte.cobertura, anclajes.UPPER_BODY)
    assert puntaje < calidad.UMBRAL_PUBLICAR
    assert razon in (calidad.RAZON_PROPORCION, calidad.RAZON_COBERTURA, calidad.RAZON_RECTANGULO)


def test_silueta_fragmentada_penaliza_fuerte():
    """Pedazos sueltos no sirven para anclar la prenda: puntaje bajo seguro."""
    mascara = Image.new("L", (200, 200), 0)
    for x, y in ((20, 20), (70, 80), (120, 40), (160, 150)):
        for dx in range(10):
            for dy in range(10):
                mascara.putpixel((x + dx, y + dy), 255)
    puntaje, razon = calidad.puntuar(mascara, 0.2, anclajes.UPPER_BODY)
    assert puntaje < calidad.UMBRAL_PUBLICAR
    assert razon == calidad.RAZON_FRAGMENTADA


# ------------------------------------------------------- flujo de revisión ---

import pytest  # noqa: E402


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    from sqlalchemy import create_engine

    monkeypatch.setattr("src.infrastructure.config.settings.settings.media_storage_dir", str(tmp_path), raising=False)
    monkeypatch.setattr("src.infrastructure.config.settings.settings.media_public_base_url", "http://test/media", raising=False)
    monkeypatch.setattr("src.infrastructure.config.settings.settings.ai_api_key", "", raising=False)

    engine = create_engine(
        "sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    from src.auth.infrastructure.persistence.models.user import UserModel
    from src.roles.infrastructure.persistence.models.permission import PermissionModel
    from src.roles.infrastructure.persistence.models.role import RoleModel
    from src.usuarios_catalogo.infrastructure.models.catalog import (
        CategoryModel,
        ColorModel,
        ProductImageModel,
        ProductModel,
        ProductVariantModel,
        SizeModel,
    )

    with Session(engine, expire_on_commit=False) as db:
        admin = UserModel(
            email="catalogo@example.test", password_hash="unused", first_name="Gestor",
            last_name="Catalogo", is_active=True, is_verified=True,
        )
        rol = RoleModel(code="catalogo", name="Gestor de catálogo")
        rol.permissions = [
            PermissionModel(code="catalog.write", name="catalog.write", module="catalog"),
            PermissionModel(code="catalog.read", name="catalog.read", module="catalog"),
        ]
        admin.roles = [rol]
        categoria = CategoryModel(name="Pantalones", slug="pantalones")
        color = ColorModel(name="Azul marino", hex_code="#1E2A44")
        otro_color = ColorModel(name="Rojo tinto", hex_code="#8E2B33")
        talla = SizeModel(code="M", name="Mediana")
        db.add_all([admin, rol, categoria, color, otro_color, talla])
        db.flush()

        def crear_producto(nombre, foto, colores):
            archivo = tmp_path / (nombre.replace(" ", "").lower() + ".png")
            archivo.write_bytes(foto)
            producto = ProductModel(
                name=nombre, slug="slug-" + nombre[:8].lower().strip(), description="prueba",
                base_price=Decimal("199"), category_id=categoria.id,
            )
            producto.images = [ProductImageModel(url=f"http://test/media/{archivo.name}", is_primary=True)]
            for orden, c in enumerate(colores):
                producto.variants.append(
                    ProductVariantModel(
                        color_id=c.id, size_id=talla.id,
                        sku=f"SKU-{nombre[:6]}{orden}", is_active=True,
                    )
                )
            db.add(producto)
            db.flush()
            return producto

        dudoso = crear_producto("Camisa angosta", foto_dudosa(), [color])
        limpio = crear_producto("Pantalón chino", foto_de_estudio(), [color, otro_color])
        db.commit()

        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: admin
        with TestClient(app) as client:
            yield client, db, dudoso, limpio, color, otro_color
    engine.dispose()


def test_un_recorte_dudoso_queda_en_revision_hasta_que_se_aprueba(mundo):
    client, db, dudoso, _, color, _ = mundo
    creado = client.post(
        f"/api/v1/vestidor/admin/products/{dudoso.id}/assets", json={"color_id": str(color.id)}
    )
    assert creado.status_code == 200, creado.text
    recurso = creado.json()["data"]
    assert recurso["ai_status"] == "review"
    assert recurso["quality_score"] is not None and recurso["quality_score"] < 60
    assert recurso["quality_reason"]
    assert recurso["preview_url"]
    assert recurso["reviewed_by"] is None

    # No se publica: el probador no lo entrega hasta que una persona lo aprueba.
    sesion = client.post(
        "/api/v1/vestidor/sessions",
        json={"product_id": str(dudoso.id), "color_id": str(color.id)},
    )
    assert sesion.status_code == 404, sesion.text

    # Aprobar lo publica.
    aprobado = client.post(
        f"/api/v1/vestidor/admin/assets/{recurso['id']}/review", json={"approve": True}
    )
    assert aprobado.status_code == 200, aprobado.text
    assert aprobado.json()["data"]["ai_status"] == "ready"
    assert aprobado.json()["data"]["reviewed_by"] is not None

    sesion = client.post(
        "/api/v1/vestidor/sessions",
        json={"product_id": str(dudoso.id), "color_id": str(color.id)},
    )
    assert sesion.status_code == 200, sesion.text


def test_rechazar_marca_fallido_y_queda_fuera_del_probador(mundo):
    client, db, dudoso, _, color, _ = mundo
    recurso = client.post(
        f"/api/v1/vestidor/admin/products/{dudoso.id}/assets", json={"color_id": str(color.id)}
    ).json()["data"]

    rechazado = client.post(
        f"/api/v1/vestidor/admin/assets/{recurso['id']}/review",
        json={"approve": False, "note": "La silueta no representa la prenda."},
    )
    assert rechazado.status_code == 200, rechazado.text
    datos = rechazado.json()["data"]
    assert datos["ai_status"] == "failed"
    assert "silueta" in datos["ai_error"]

    sesion = client.post(
        "/api/v1/vestidor/sessions",
        json={"product_id": str(dudoso.id), "color_id": str(color.id)},
    )
    assert sesion.status_code == 404, sesion.text


def test_la_cola_de_revision_lista_solo_los_dudosos(mundo):
    client, db, dudoso, limpio, color, otro_color = mundo
    client.post(
        f"/api/v1/vestidor/admin/products/{dudoso.id}/assets", json={"color_id": str(color.id)}
    )
    client.post(
        f"/api/v1/vestidor/admin/products/{limpio.id}/assets", json={"color_id": str(color.id)}
    )

    cola = client.get("/api/v1/vestidor/admin/assets?status=review")
    assert cola.status_code == 200, cola.text
    recursos = cola.json()["data"]
    assert len(recursos) == 1
    assert recursos[0]["product_id"] == str(dudoso.id)


def test_reintento_vuelve_a_analizar_y_limpia_la_revision(mundo):
    client, db, dudoso, _, color, _ = mundo
    recurso = client.post(
        f"/api/v1/vestidor/admin/products/{dudoso.id}/assets", json={"color_id": str(color.id)}
    ).json()["data"]
    client.post(f"/api/v1/vestidor/admin/assets/{recurso['id']}/review", json={"approve": False})

    reintentado = client.post(f"/api/v1/vestidor/admin/assets/{recurso['id']}/retry")
    assert reintentado.status_code == 200, reintentado.text
    datos = reintentado.json()["data"]
    assert datos["ai_status"] == "review"  # vuelve a ser la tira atípica
    assert datos["reviewed_by"] is None  # y espera revisión de nuevo


def test_preparacion_masiva_procesa_por_colores_activos(mundo):
    client, db, dudoso, limpio, color, otro_color = mundo

    lote = client.post(
        "/api/v1/vestidor/admin/bulk-prepare", json={"product_ids": [str(dudoso.id), str(limpio.id)]}
    )
    assert lote.status_code == 200, lote.text
    resumen = lote.json()["data"]
    assert resumen["processed"] >= 3  # 1 color del dudoso + 2 del limpio
    assert resumen["review"] == 1  # el dudoso queda en revisión
    assert resumen["ready"] == 2  # ambos colores del limpio quedan listos
    assert resumen["errors"] == 0


def test_preparacion_masiva_solo_pendientes_no_toca_los_listos(mundo):
    client, db, dudoso, limpio, color, otro_color = mundo
    client.post(
        f"/api/v1/vestidor/admin/products/{limpio.id}/assets", json={"color_id": str(color.id)}
    )

    lote = client.post(
        "/api/v1/vestidor/admin/bulk-prepare",
        json={"product_ids": [str(limpio.id)], "only_pending": True},
    )
    resumen = lote.json()["data"]
    # El color listo ya está, el segundo color sigue pendiente: solo procesa ese.
    assert resumen["processed"] == 1
    assert resumen["ready"] == 1


def test_una_foto_sin_fondo_liso_no_rompe_el_lote(mundo):
    client, db, dudoso, limpio, color, otro_color = mundo
    lote = client.post("/api/v1/vestidor/admin/bulk-prepare")
    assert lote.status_code == 200, lote.text
    resumen = lote.json()["data"]
    assert resumen["errors"] == 0


def test_calidad_entre_cero_y_cien():
    recorte = segmentacion.recortar_fondo(foto_de_estudio())
    puntaje, _ = calidad.puntuar(recorte.mascara, recorte.cobertura, anclajes.LOWER_BODY)
    assert 0 <= puntaje <= 100