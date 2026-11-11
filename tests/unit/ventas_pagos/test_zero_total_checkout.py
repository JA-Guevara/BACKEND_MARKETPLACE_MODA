from src.ventas_pagos.application.promotions import PromotionService
from src.ventas_pagos.application.service import CommerceService
from src.ventas_pagos.infrastructure.models import CartItemModel
from src.ventas_pagos.web.schemas import Address, CheckoutOrder
from tests.unit.reservas.test_create_reserva_idempotencia import make_world


def test_pedido_cubierto_por_descuento_no_abre_stripe(monkeypatch):
    db, world = make_world()
    db.add(CartItemModel(user_id=world["actor"].id, variant_id=world["variant"].id, quantity=1))
    db.commit()

    def full_discount(self, user, items, coupon_code=None, *, lock=False):
        return {"subtotal": "50.00", "discount_total": "50.00", "total": "0.00",
                "discounts": [], "coupon_code": None}

    monkeypatch.setattr(PromotionService, "quote", full_discount)
    data = CheckoutOrder(
        branch_id=world["branch"].id, payment_method="stripe",
        address=Address(recipient="Ana", phone="77712345", line1="Calle 123",
                        city="Santa Cruz", country="BO"),
    )
    service = CommerceService(db)
    order = service.create_order(world["actor"], data)
    assert order.total == 0
    assert order.status == "paid" and order.payment_status == "paid"
    assert service.checkout(order) == {"status": "paid", "url": None}


def test_create_order_idempotencia_con_client_request_id():
    from uuid import uuid4
    db, world = make_world()
    db.add(CartItemModel(user_id=world["actor"].id, variant_id=world["variant"].id, quantity=1))
    db.commit()

    req_id = uuid4()
    data = CheckoutOrder(
        branch_id=world["branch"].id, payment_method="manual",
        address=Address(recipient="Ana", phone="77712345", line1="Calle 123",
                        city="Santa Cruz", country="BO"),
        client_request_id=req_id,
    )
    service = CommerceService(db)
    order1 = service.create_order(world["actor"], data)
    assert order1.client_request_id == req_id

    # Segundo intento con el mismo client_request_id: retorna la orden existente sin duplicar ni descontar stock extra
    order2 = service.create_order(world["actor"], data)
    assert order2.id == order1.id
    assert order2.number == order1.number

