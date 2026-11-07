from decimal import Decimal
from types import SimpleNamespace
import pytest
from src.ventas_pagos.domain.returns import paid_credit


@pytest.mark.parametrize('quantity,total',[(3,'100.00'),(7,'100.01'),(3,'0.01')])
def test_partial_returns_allocate_every_paid_cent_once(quantity,total):
    order=SimpleNamespace(total=Decimal(total),items=[{'variant_id':'M','quantity':quantity,'unit_price':'100.00'}])
    prior=[];credits=[]
    for _ in range(quantity):
        credits.append(paid_credit(order,'M',1,prior))
        prior.append(SimpleNamespace(status='completed',items=[{'variant_id':'M','quantity':1}]))
    assert all(amount>=0 for amount in credits)
    assert sum(credits)==Decimal(total)
    assert paid_credit(order,'M',quantity,[])==Decimal(total)


def test_line_discounts_do_not_create_or_lose_money_between_garments():
    order=SimpleNamespace(total=Decimal('99.99'),items=[{'variant_id':'M','quantity':3,'unit_price':'100.00'},
        {'variant_id':'L','quantity':2,'unit_price':'80.00'}])
    assert paid_credit(order,'M',3,[])+paid_credit(order,'L',2,[])==order.total
