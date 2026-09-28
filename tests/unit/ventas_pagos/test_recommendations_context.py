from datetime import date, timedelta
from decimal import Decimal

from src.usuarios_catalogo.infrastructure.models.catalog import (
    ColorModel, ProductModel, ProductVariantModel, SeasonModel, SizeModel,
)
from src.ventas_pagos.application.service import CommerceService
from src.ventas_pagos.infrastructure.models import StockModel
from tests.unit.reservas.test_create_reserva_idempotencia import make_world


def test_recommendations_respect_branch_size_season_and_live_stock():
    db, world = make_world()
    original = world["variant"].product
    branch = world["branch"]
    size = SizeModel(code="L", name="Grande")
    color = ColorModel(name="Azul", hex_code="#0000FF")
    season = SeasonModel(
        name="Actual", start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=1),
    )
    db.add_all([size, color, season])
    db.flush()
    suggested = ProductModel(
        name="Vestido azul", slug="vestido-azul", description="Prueba",
        base_price=Decimal("50"), category_id=original.category_id,
        season_id=season.id, is_active=True,
    )
    variant = ProductVariantModel(
        product=suggested, size_id=size.id, color_id=color.id, sku="VES-L-002",
    )
    db.add_all([suggested, variant])
    db.flush()
    stock = StockModel(variant_id=variant.id, branch_id=branch.id, quantity=2)
    db.add(stock)
    db.commit()
    service = CommerceService(db)

    matches = service.recommendations(
        None, branch_id=branch.id, size_id=size.id,
        season_id=season.id, product_id=original.id,
    )
    assert [row["id"] for row in matches] == [str(suggested.id)]

    stock.quantity = 0
    db.commit()
    assert service.recommendations(
        None, branch_id=branch.id, size_id=size.id,
        season_id=season.id, product_id=original.id,
    ) == []
