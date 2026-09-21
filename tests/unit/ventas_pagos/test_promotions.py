from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from src.ventas_pagos.application.promotions import PromotionService


class _Rows:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows


class _Db:
    def __init__(self, rows): self.rows = rows
    def scalars(self, _query): return _Rows(self.rows)


def promo(**changes):
    values = dict(
        id="promo-1", code=None, name="Temporada", discount_type="percent",
        discount_value=Decimal("10"), minimum_order=Decimal("100"), category_id=None,
        product_id=None, customer_scope="all", minimum_paid_orders=0, starts_at=None,
        ends_at=None, max_uses=None, uses_count=0, per_user_limit=None, is_active=True,
    )
    values.update(changes)
    return SimpleNamespace(**values)


def test_uses_best_automatic_promotion_and_valid_coupon():
    auto = promo(id="auto", discount_value=Decimal("10"))
    code = promo(id="coupon", code="LOOK20", name="Cupón", discount_value=Decimal("20"))
    service = PromotionService(_Db([auto, code]))
    quote = service.quote(SimpleNamespace(id="user"), [{"line_total": "200", "product_id": "p", "category_id": "c"}], "look20")
    assert quote["subtotal"] == "200.00"
    # Se aplican en secuencia: 10% de 200 y luego 20% sobre los 180 restantes.
    assert quote["discount_total"] == "56.00"
    assert quote["total"] == "144.00"
    assert {row["name"] for row in quote["discounts"]} == {"Temporada", "Cupón"}


def test_ignores_expired_automatic_promotion():
    expired = promo(ends_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    quote = PromotionService(_Db([expired])).quote(SimpleNamespace(id="user"), [{"line_total": "200", "product_id": "p", "category_id": "c"}])
    assert quote["discount_total"] == "0.00"
    assert quote["total"] == "200.00"
