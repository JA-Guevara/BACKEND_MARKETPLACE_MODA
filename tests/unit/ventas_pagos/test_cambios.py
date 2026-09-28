import uuid

import pytest
from sqlalchemy import select

from src.shared.exceptions.domain_exception import ConflictError, ValidationError
from src.usuarios_catalogo.infrastructure.models.catalog import ProductVariantModel, SizeModel
from src.ventas_pagos.application.returns_service import ReturnsService
from src.ventas_pagos.infrastructure.models import StockModel
from src.ventas_pagos.web.schemas import ExchangeRequest, ReturnResolution
from src.notificaciones.domain.plantillas import devolucion_estado
from tests.unit.ventas_pagos.test_devoluciones import make_order, make_world


def setup():
    db, world = make_world()
    order = make_order(db, world, cantidad=2)
    size = SizeModel(code="L", name="Grande")
    db.add(size)
    db.flush()
    replacement = ProductVariantModel(
        product_id=world["variant"].product_id, size_id=size.id,
        color_id=world["variant"].color_id, sku="POL-L-002",
    )
    db.add(replacement)
    db.flush()
    stock = StockModel(variant_id=replacement.id, branch_id=world["branch"].id, quantity=2)
    db.add(stock)
    db.commit()
    request = ExchangeRequest(
        reason="Necesito otra talla.", variant_id=world["variant"].id,
        replacement_variant_id=replacement.id, quantity=1,
        client_request_id=uuid.uuid4(),
    )
    return db, world, order, replacement, stock, request


def test_cambio_aparta_reemplazo_y_retorna_original_solo_al_recibirlo():
    db, world, order, replacement, stock, request = setup()
    service = ReturnsService(db)
    assert service.opciones_cambio(order, world["variant"].id)[0]["variant_id"] == str(replacement.id)
    cambio = service.solicitar_cambio(world["cliente"], order, request)
    db.refresh(stock)
    assert stock.quantity == 1
    assert cambio.refund_amount == 0
    assert service.solicitar_cambio(world["cliente"], order, request).id == cambio.id
    db.refresh(stock)
    assert stock.quantity == 1
    service.resolver(world["admin"], cambio, ReturnResolution(status="approved"))
    service.resolver(world["admin"], cambio, ReturnResolution(status="completed"))
    original = db.scalar(select(StockModel).where(StockModel.variant_id == world["variant"].id))
    assert original.quantity == 6
    db.refresh(stock)
    assert stock.quantity == 1


def test_rechazo_libera_reemplazo_y_permite_nueva_solicitud():
    db, world, order, _, stock, request = setup()
    service = ReturnsService(db)
    cambio = service.solicitar_cambio(world["cliente"], order, request)
    service.resolver(world["admin"], cambio, ReturnResolution(status="rejected", note="No cumple condiciones."))
    db.refresh(stock)
    assert stock.quantity == 2
    assert service.devolvible(order)["units"][str(world["variant"].id)] == 2


def test_no_permite_reemplazo_sin_stock_ni_precio_igual():
    db, world, order, replacement, stock, request = setup()
    stock.quantity = 0
    db.commit()
    with pytest.raises(ConflictError):
        ReturnsService(db).solicitar_cambio(world["cliente"], order, request)
    stock.quantity = 2
    replacement.price_override = 120
    db.commit()
    with pytest.raises(ConflictError):
        ReturnsService(db).solicitar_cambio(world["cliente"], order, request)


def test_no_permite_mas_unidades_que_el_pedido():
    db, world, order, _, _, request = setup()
    request.quantity = 3
    with pytest.raises(ValidationError):
        ReturnsService(db).solicitar_cambio(world["cliente"], order, request)


def test_aviso_de_cambio_no_promete_un_reembolso():
    message = devolucion_estado(
        codigo="C-1", numero_pedido="FS-1", estado="approved",
        items=[{"name": "Polera M", "quantity": 1, "unit_price": "100.00",
                "replacement_name": "Polera L", "replacement_size": "L",
                "replacement_color": "Azul"}],
        monto="0.00", cambio=True, metodo_reembolso="stripe",
    )
    assert "cambio" in message.asunto.lower()
    assert "reintegro" not in message.html.lower()
    assert "reembolso" not in message.html.lower()
