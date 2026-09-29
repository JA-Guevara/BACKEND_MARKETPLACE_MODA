"""Subida de imágenes: el reprocesado con Pillow salió del bucle de eventos.

`upload_image` pasó de `async def` a `def` para que Pillow (decodificar, rotar
por EXIF, redimensionar y recomprimir a WEBP) y el commit de la bitácora corran
en el pool de hilos de FastAPI en vez de congelar el proceso entero. El endpoint
no tenía ninguna prueba, así que estas fijan el contrato observable: 201, el
sobre {success,message,data}, el mismo mensaje de validación y el archivo WEBP
realmente escrito en disco.
"""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.infrastructure.config.settings import settings
from src.infrastructure.database.base import Base
from src.infrastructure.database.session import get_db
from src.main import create_app
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.roles.infrastructure.persistence.models.role import RoleModel

RUTA = '/api/v1/media/images'


def _png(ancho=40, alto=30) -> bytes:
    buffer = BytesIO()
    Image.new('RGB', (ancho, alto), (116, 57, 78)).save(buffer, 'PNG')
    return buffer.getvalue()


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'media_storage_dir', str(tmp_path), raising=False)
    monkeypatch.setattr(settings, 'media_public_base_url', 'http://test/media', raising=False)
    engine = create_engine('sqlite+pysqlite:///:memory:', poolclass=StaticPool,
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        gestor = UserModel(email='catalogo@example.test', password_hash='unused', first_name='Gestor',
                           last_name='Catalogo', is_active=True, is_verified=True)
        rol = RoleModel(code='catalogo', name='Gestor de catálogo')
        rol.permissions = [PermissionModel(code='catalog.write', name='catalog.write', module='catalog')]
        gestor.roles = [rol]
        db.add_all([gestor, rol])
        db.commit()
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: gestor
        with TestClient(app) as client:
            yield client, db, Path(tmp_path)
    engine.dispose()


def test_la_imagen_se_reprocesa_y_queda_guardada_como_webp(mundo):
    client, db, carpeta = mundo
    respuesta = client.post(RUTA, files={'file': ('prenda.png', _png(), 'image/png')})
    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo['success'] is True and cuerpo['message'] == 'Imagen cargada.'
    datos = cuerpo['data']
    assert datos['width'] == 40 and datos['height'] == 30
    assert datos['name'].endswith('.webp')
    assert datos['url'] == f"http://test/media/{datos['name']}"
    assert (carpeta / datos['name']).is_file()
    evento = db.scalar(select(AuditEventModel).where(AuditEventModel.action == 'catalog.image_uploaded'))
    assert evento is not None and evento.entity_id == datos['name']


def test_un_archivo_que_no_es_imagen_sigue_dando_el_mismo_mensaje(mundo):
    client, _, _ = mundo
    respuesta = client.post(RUTA, files={'file': ('prenda.png', b'esto no es una imagen', 'image/png')})
    assert respuesta.status_code == 422
    assert respuesta.json()['error']['message'] == 'El archivo no es una imagen válida o segura.'


def test_el_tope_de_megabytes_sigue_cortando_la_lectura(mundo, monkeypatch):
    # La lectura síncrona pide un byte de más que el límite, igual que antes:
    # así se rechaza sin traer a memoria un archivo enorme.
    client, _, _ = mundo
    monkeypatch.setattr(settings, 'media_max_upload_mb', 1, raising=False)
    respuesta = client.post(RUTA, files={'file': ('grande.png', b'x' * (1024 * 1024 + 10), 'image/png')})
    assert respuesta.status_code == 422
    assert respuesta.json()['error']['message'] == 'La imagen debe pesar entre 1 byte y 1 MB.'
