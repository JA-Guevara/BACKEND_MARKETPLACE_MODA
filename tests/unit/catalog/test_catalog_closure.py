from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from src.main import app  # Register every mapped model; no external services are called.
from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.base import Base
from src.inventario_sucursales.infrastructure.models.organization import BranchModel, CityModel, SupplierModel
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.shared.bulk.router import authorize
from src.shared.bulk.service import process, resource_for, workbook_for
from src.shared.bulk.workbook import build_workbook, read_rows
from src.shared.exceptions.domain_exception import AuthorizationError, ConflictError
from src.usuarios_catalogo.application.services.catalog_service import CatalogService
from src.usuarios_catalogo.infrastructure.models.catalog import ProductVariantModel, SizeModel
from src.usuarios_catalogo.web.schemas.catalog import CategoryCreate, CategoryUpdate, ColorCreate, ProductCreate, ProductSupplierInput, ProductUpdate, SizeCreate, VariantCreate, VariantUpdate
from src.ventas_pagos.infrastructure.models import CartItemModel, OrderModel, StockModel


@pytest.fixture
def fixture():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as db:
        actor = UserModel(email='catalog@example.test', password_hash='unused', first_name='Cat', last_name='Test')
        city = CityModel(name='Santa Cruz', department='Santa Cruz', country='Bolivia')
        db.add_all([actor, city]); db.flush()
        branch = BranchModel(code='SCZ', name='Central', city_id=city.id, address='Centro')
        db.add(branch); db.commit()
        service = CatalogService(db)
        category = service.create_category(CategoryCreate(name='Camisas'), actor)
        size = service.create_size(SizeCreate(code='M', name='Mediana'), actor)
        color = service.create_color(ColorCreate(name='Azul', hex_code='#123456'), actor)
        product = service.create_product(ProductCreate(name='Camisa lino', description='Camisa fresca de lino', base_price=100,
            category_id=category.id, variants=[VariantCreate(size_id=size.id, color_id=color.id, sku='LINO-M')]), actor)
        yield db, actor, service, product, branch
    engine.dispose()


def test_rename_preserves_public_links_and_bulk_keys(fixture):
    db, actor, service, product, _ = fixture
    original = product.slug
    updated = service.update_product(product.id, ProductUpdate(name='Camisa mejorada'), actor)
    assert updated.slug == original
    category = product.category
    original_category = category.slug
    assert service.update_category(category.id, CategoryUpdate(name='Nuevas camisas'), actor).slug == original_category
    assert service.update_product(product.id, ProductUpdate(slug='enlace-elegido'), actor).slug == 'enlace-elegido'


def test_supplier_edit_keeps_identity_and_accepts_same_supplier(fixture):
    db, actor, service, product, _ = fixture
    supplier = SupplierModel(business_name='Textiles', tax_id='00123')
    db.add(supplier); db.commit()
    first = service.set_suppliers(product.id, [ProductSupplierInput(supplier_id=supplier.id, unit_cost=10)], actor)
    link_id = first.suppliers[0].id
    second = service.set_suppliers(product.id, [ProductSupplierInput(supplier_id=supplier.id, unit_cost=25, is_primary=True)], actor)
    assert second.suppliers[0].id == link_id
    assert second.suppliers[0].unit_cost == Decimal('25')
    assert second.suppliers[0].is_primary


@pytest.mark.parametrize('source', ['stock', 'cart', 'order', 'reservation'])
def test_used_variant_cannot_be_deleted_but_can_be_deactivated(fixture, source):
    db, actor, service, product, branch = fixture
    variant = product.variants[0]
    if source == 'stock':
        row = StockModel(variant_id=variant.id, branch_id=branch.id, quantity=0)
    elif source == 'cart':
        row = CartItemModel(user_id=actor.id, variant_id=variant.id, quantity=1)
    elif source == 'order':
        row = OrderModel(number='FS-TEST', user_id=actor.id, customer_email=actor.email, branch_id=branch.id,
            payment_method='cash', total=100, currency='BOB', address={}, items=[{'variant_id': str(variant.id), 'quantity': 1}])
    else:
        row = ReservationModel(user_id=actor.id, branch_id=branch.id, scheduled_at=datetime.now(timezone.utc),
            items=[{'variant_id': str(variant.id), 'quantity': 1}])
    db.add(row); db.commit()
    with pytest.raises(ConflictError, match='Desactivala'):
        service.delete_variant(product.id, variant.id, actor)
    assert db.get(ProductVariantModel, variant.id) is not None
    service.update_variant(product.id, variant.id, VariantUpdate(is_active=False), actor)
    assert variant.is_active is False
    assert db.get(type(row), row.id) is row


def test_unused_variant_can_be_deleted(fixture):
    db, actor, service, product, _ = fixture
    variant_id = product.variants[0].id
    service.delete_variant(product.id, variant_id, actor)
    assert db.get(ProductVariantModel, variant_id) is None


def excel_rows(name, rows):
    resource = resource_for(name)
    return build_workbook(resource.columns, rows, {}, [])


def test_bulk_preview_is_read_only_and_confirmation_is_atomic(fixture):
    db, actor, *_ = fixture
    resource = resource_for('sizes')
    content = excel_rows('sizes', [{'code': 'S', 'name': 'Pequeña', 'sort_order': 1}, {'code': 'L', 'name': 'Grande', 'sort_order': 3}])
    before = db.scalar(select(func.count()).select_from(SizeModel))
    preview = process(db, resource, actor, content, 'create')
    assert preview['valid'] == 2 and preview['imported'] == 0
    assert db.scalar(select(func.count()).select_from(SizeModel)) == before
    saved = process(db, resource, actor, content, 'create', confirm=True)
    assert saved['imported'] == 2
    assert db.scalar(select(func.count()).select_from(SizeModel)) == before + 2


def test_bulk_invalid_row_rolls_back_entire_batch(fixture):
    db, actor, *_ = fixture
    content = excel_rows('sizes', [{'code': 'XL', 'name': 'Extra grande'}, {'code': 'M', 'name': 'Duplicada'}])
    result = process(db, resource_for('sizes'), actor, content, 'create', confirm=True)
    assert result['imported'] == 0 and result['errors'][0]['row'] == 3
    assert db.scalar(select(SizeModel).where(SizeModel.code == 'XL')) is None


def test_bulk_update_preserves_empty_fields_and_export_round_trips(fixture):
    db, actor, *_ = fixture
    content = excel_rows('sizes', [{'code': 'M', 'name': 'Nueva mediana', 'sort_order': None}])
    result = process(db, resource_for('sizes'), actor, content, 'update', confirm=True)
    assert result['imported'] == 1
    exported = workbook_for(db, resource_for('sizes'))
    rows = read_rows(exported, resource_for('sizes').columns)
    assert rows[0][1] == {'code': 'M', 'name': 'Nueva mediana', 'sort_order': 0}


def test_bulk_client_cannot_import_or_export(fixture):
    _, actor, *_ = fixture
    for action in ('read', 'write'):
        with pytest.raises(AuthorizationError):
            authorize('products', actor, action)


def test_excel_export_keeps_formula_like_text_inert():
    content = excel_rows('sizes', [{'code': 'XS', 'name': '=HYPERLINK("https://example.test")'}])
    book = load_workbook(BytesIO(content))
    assert book['Datos']['B2'].data_type == 's'
    book.close()
