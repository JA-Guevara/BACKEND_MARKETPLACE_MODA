"""Las cargas de Excel siguen funcionando con la lectura síncrona del archivo.

`preview` e `import_excel` dejaron de ser `async def` (openpyxl y las escrituras
congelaban el bucle de eventos) y `read_file` pasó a leer del archivo temporal
con `file.file.read()`. Estas pruebas recorren la ruta HTTP real -multipart
incluido- para comprobar que ese cambio no alteró nada de lo observable: mismos
códigos, mismos mensajes y el mismo tope de 5 MB.
"""

from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.base import Base
from src.infrastructure.database.session import get_db
from src.main import create_app
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.roles.infrastructure.persistence.models.role import RoleModel
from src.shared.bulk import router as bulk_router
from src.shared.bulk.service import resource_for
from src.shared.bulk.workbook import build_workbook
from src.usuarios_catalogo.infrastructure.models.catalog import SizeModel

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


@pytest.fixture
def mundo():
    engine = create_engine('sqlite+pysqlite:///:memory:', poolclass=StaticPool,
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        gestor = UserModel(email='catalogo@example.test', password_hash='unused', first_name='Gestor',
                           last_name='Catalogo', is_active=True, is_verified=True)
        # Rol real: así la autorización del router se ejercita de verdad.
        rol = RoleModel(code='catalogo', name='Gestor de catálogo')
        rol.permissions = [
            PermissionModel(code='catalog.read', name='catalog.read', module='catalog'),
            PermissionModel(code='catalog.write', name='catalog.write', module='catalog'),
        ]
        gestor.roles = [rol]
        db.add_all([gestor, rol])
        db.commit()
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: gestor
        with TestClient(app) as client:
            yield client, db
    engine.dispose()


def _libro(filas):
    return build_workbook(resource_for('sizes').columns, filas, {}, [])


def _subir(client, ruta, contenido, datos=None, nombre='tallas.xlsx'):
    return client.post(ruta, files={'file': (nombre, contenido, XLSX)}, data=datos or {})


def test_la_vista_previa_lee_el_archivo_y_no_guarda_nada(mundo):
    client, db = mundo
    contenido = _libro([{'code': 'S', 'name': 'Pequeña', 'sort_order': 1}])
    respuesta = _subir(client, '/api/v1/bulk/sizes/preview', contenido, {'mode': 'create'})
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo['message'] == 'Vista previa sin guardar.'
    assert cuerpo['data']['valid'] == 1 and cuerpo['data']['imported'] == 0
    assert db.scalar(select(SizeModel).where(SizeModel.code == 'S')) is None


def test_la_importacion_confirmada_guarda_las_filas(mundo):
    client, db = mundo
    contenido = _libro([{'code': 'L', 'name': 'Grande', 'sort_order': 3}])
    respuesta = _subir(client, '/api/v1/bulk/sizes/import', contenido, {
        'mode': 'create',
        'preview_digest': sha256(contenido).hexdigest(),
        'confirm': 'true',
    })
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()['message'] == 'Importación completada.'
    assert db.scalar(select(SizeModel).where(SizeModel.code == 'L')) is not None


def test_un_archivo_que_no_es_xlsx_sigue_dando_el_mismo_mensaje(mundo):
    client, _ = mundo
    respuesta = _subir(client, '/api/v1/bulk/sizes/preview', b'no soy un libro',
                       {'mode': 'create'}, nombre='tallas.csv')
    assert respuesta.status_code == 422
    assert respuesta.json()['error']['message'] == 'Seleccioná un archivo .xlsx.'


def test_el_tope_de_tamano_sigue_cortando_la_lectura(mundo, monkeypatch):
    # Se baja el tope en vez de subir 5 MB de verdad: lo que se comprueba es que
    # la lectura síncrona sigue pidiendo un byte de más y detecta el exceso.
    client, _ = mundo
    monkeypatch.setattr(bulk_router, 'MAX_BYTES', 64)
    contenido = _libro([{'code': 'XL', 'name': 'Extra grande', 'sort_order': 4}])
    assert len(contenido) > 64
    respuesta = _subir(client, '/api/v1/bulk/sizes/preview', contenido, {'mode': 'create'})
    assert respuesta.status_code == 422
    assert respuesta.json()['error']['message'] == 'Máximo 5 MB por archivo.'
