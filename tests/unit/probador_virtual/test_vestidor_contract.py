"""Contrato del probador manual: HTTP y SQLite descartable, sin cámara ni APIs externas."""
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.main import create_app
from src.auth.web.dependencies import get_current_user, get_optional_user
from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.infrastructure.database.base import Base
from src.infrastructure.database.session import get_db
from src.usuarios_catalogo.infrastructure.models.catalog import ARAssetModel, CategoryModel, ProductModel


@pytest.fixture
def world():
    engine = create_engine('sqlite+pysqlite:///:memory:', poolclass=StaticPool,
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = UserModel(email='vestidor@example.test', password_hash='unused', first_name='Prueba',
                         last_name='Probador', is_active=True, is_verified=True)
        category = CategoryModel(name='Prendas de prueba', slug='prendas-prueba')
        db.add_all([user, category])
        db.flush()
        product = ProductModel(name='Polera prueba', slug='polera-prueba', description='Prueba aislada',
                               base_price=Decimal('50'), category_id=category.id)
        product.ar_assets = [
            ARAssetModel(asset_type='glb', asset_url='https://example.test/model.glb'),
            ARAssetModel(asset_type='image_overlay', asset_url='https://example.test/disabled.webp', is_active=False),
            ARAssetModel(asset_type='image_overlay', asset_url='https://example.test/active.webp'),
        ]
        db.add(product)
        db.commit()
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_optional_user] = lambda: user
        with TestClient(app) as client:
            yield client, db, product, user, app
    engine.dispose()


def test_resuelve_imagen_activa_y_registra_actor(world):
    client, db, product, user, _ = world
    result = client.post('/api/v1/vestidor/sessions', json={'product_id': str(product.id)})
    assert result.status_code == 200
    data = result.json()['data']
    assert data['product_id'] == str(product.id)
    assert data['asset_type'] == 'image_overlay'
    assert data['asset_url'] == 'https://example.test/active.webp'
    db.expire_all()
    events = list(db.scalars(select(AuditEventModel).where(AuditEventModel.action == 'probador_virtual.session_started')))
    assert len(events) == 1
    assert events[0].actor_user_id == user.id
    assert events[0].entity_id == str(product.id)


def test_sin_imagen_activa_no_registra_exito(world):
    client, db, product, _, _ = world
    for asset in product.ar_assets:
        if asset.asset_type == 'image_overlay':
            asset.is_active = False
    db.commit()
    result = client.post('/api/v1/vestidor/sessions', json={'product_id': str(product.id)})
    assert result.status_code == 404
    assert not list(db.scalars(select(AuditEventModel)))


def test_prenda_inactiva_o_inexistente_no_se_prueba(world):
    client, db, product, _, _ = world
    product.is_active = False
    db.commit()
    for product_id in (product.id, uuid.uuid4()):
        assert client.post('/api/v1/vestidor/sessions', json={'product_id': str(product_id)}).status_code == 404
    assert not list(db.scalars(select(AuditEventModel)))


def test_bitacora_conserva_actor_si_hay_sesion_y_permite_visita_publica(world):
    client, db, product, _, app = world
    assert client.post('/api/v1/vestidor/sessions', json={'product_id': 'invalid'}).status_code == 422
    del app.dependency_overrides[get_optional_user]
    response = client.post('/api/v1/vestidor/sessions', json={'product_id': str(product.id)})
    assert response.status_code == 200
    db.expire_all()
    event = db.scalars(select(AuditEventModel).where(
        AuditEventModel.action == 'probador_virtual.session_started'
    )).first()
    assert event is not None and event.actor_user_id is None
