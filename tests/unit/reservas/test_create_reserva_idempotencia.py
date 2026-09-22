"""Regresiones QA de idempotencia en reservas: la misma clave con el mismo
detalle devuelve la reserva ya registrada; la misma clave con detalle distinto
avisa en vez de devolver en silencio la anterior."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.base import Base
from src.inventario_sucursales.application.services.organization_service import OrganizationService
from src.inventario_sucursales.web.schemas.organization import BranchCreate, CityCreate
from src.reservas.application.use_cases.create_reserva import CrearReserva
from src.reservas.infrastructure.http.schemas import CrearReservaRequest, ReservaItemInput
from src.reservas.web.router import reserva_data
from src.shared.exceptions.domain_exception import ValidationError
from src.usuarios_catalogo.application.services.catalog_service import CatalogService
from src.usuarios_catalogo.web.schemas.catalog import CategoryCreate, ColorCreate, ProductCreate, SizeCreate, VariantCreate
from src.ventas_pagos.infrastructure.models import StockModel


def make_world() -> tuple[Session, dict]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    actor = UserModel(email="cliente@fashionstore.test", password_hash="x", first_name="Ana", last_name="Lopez",
                      is_active=True, is_verified=True)
    db.add(actor)
    db.flush()
    org = OrganizationService(db)
    city = org.create_city(CityCreate(name="Santa Cruz", department="Santa Cruz"), actor)
    branch = org.create_branch(BranchCreate(code="SCZ-01", name="Sucursal Central", city_id=city.id, address="Av. 1"), actor)
    catalog = CatalogService(db)
    category = catalog.create_category(CategoryCreate(name="Vestidos"), actor)
    size = catalog.create_size(SizeCreate(code="M", name="Mediana", sort_order=20), actor)
    color = catalog.create_color(ColorCreate(name="Rojo", hex_code="#FF0000"), actor)
    product = catalog.create_product(ProductCreate(
        name="Vestido primavera", description="descripcion de QA", brand="FashionStore", gender="mujer", base_price=Decimal("50"),
        category_id=category.id, variants=[VariantCreate(size_id=size.id, color_id=color.id, sku="VES-001")]), actor)
    variant = product.variants[0]
    db.add(StockModel(variant_id=variant.id, branch_id=branch.id, quantity=20))
    db.commit()
    return db, {"actor": actor, "branch": branch, "variant": variant}


def request(branch_id, variant_id, client_key, quantity=1, when=None):
    when = when or (datetime.now(timezone.utc) + timedelta(days=2)).replace(tzinfo=None)
    return CrearReservaRequest(
        branch_id=branch_id,
        scheduled_at=when,
        items=[ReservaItemInput(variant_id=variant_id, quantity=quantity)],
        notes="",
        client_key=client_key,
    )


def test_misma_clave_mismo_detalle_devuelve_la_misma_reserva():
    db, world = make_world()
    user, branch, variant = world["actor"], world["branch"], world["variant"]
    key = str(uuid.uuid4())
    data = request(branch.id, variant.id, key)
    first = CrearReserva(db).execute(user, data)
    second = CrearReserva(db).execute(user, data)
    assert first.id == second.id


def test_misma_clave_con_detalle_distinto_avisa():
    db, world = make_world()
    user, branch, variant = world["actor"], world["branch"], world["variant"]
    key = str(uuid.uuid4())
    before = request(branch.id, variant.id, key, quantity=1)
    CrearReserva(db).execute(user, before)
    with pytest.raises(ValidationError):
        CrearReserva(db).execute(user, request(branch.id, variant.id, key, quantity=2))


def test_claves_distintas_crean_reservas_distintas():
    db, world = make_world()
    user, branch, variant = world["actor"], world["branch"], world["variant"]
    a = CrearReserva(db).execute(user, request(branch.id, variant.id, str(uuid.uuid4()), quantity=1))
    b = CrearReserva(db).execute(user, request(branch.id, variant.id, str(uuid.uuid4()), quantity=1))
    assert a.id != b.id


def test_reserva_aparta_y_luego_libera_unidades_al_ser_atendida():
    from src.reservas.application.use_cases.confirm_reserva import ActualizarEstadoReserva
    from sqlalchemy import select
    db, world = make_world()
    user, branch, variant = world["actor"], world["branch"], world["variant"]
    reserva = CrearReserva(db).execute(user, request(branch.id, variant.id, str(uuid.uuid4()), quantity=2))
    stock = db.scalar(select(StockModel).where(StockModel.variant_id == variant.id, StockModel.branch_id == branch.id))
    assert reserva.inventory_held and stock.quantity == 18
    states = ActualizarEstadoReserva(db)
    states.execute(reserva, "confirmed", user)
    states.execute(reserva, "ready", user)
    states.execute(reserva, "attended", user)
    db.refresh(stock)
    assert not reserva.inventory_held and stock.quantity == 20


def test_respuesta_de_reserva_muestra_sucursal_y_recupera_snapshot_historico():
    db, world = make_world()
    user, branch, variant = world["actor"], world["branch"], world["variant"]
    reserva = CrearReserva(db).execute(user, request(branch.id, variant.id, str(uuid.uuid4())))

    # Simula una reserva creada antes de que se guardaran snapshots completos.
    reserva.items = [{"variant_id": str(variant.id), "quantity": 1}]
    data = reserva_data(reserva, db)

    assert data["branch_name"] == "Sucursal Central"
    assert data["items"] == [{
        "variant_id": str(variant.id),
        "quantity": 1,
        "product_id": str(variant.product_id),
        "name": "Vestido primavera",
        "sku": "VES-001",
        "size": "Mediana",
        "color": "Rojo",
        "image_url": None,
    }]
