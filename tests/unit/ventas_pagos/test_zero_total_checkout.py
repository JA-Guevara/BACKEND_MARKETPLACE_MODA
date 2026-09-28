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
