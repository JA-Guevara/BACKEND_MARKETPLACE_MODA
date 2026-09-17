"""Core regression tests for cashier sales and the stock movement ledger."""
import uuid
from sqlalchemy import select

from src.inventario_sucursales.application.services.organization_service import OrganizationService
from src.inventario_sucursales.web.schemas.organization import CashPointCreate
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.ventas_pagos.application.service import CommerceService
from src.ventas_pagos.infrastructure.models import StockModel, StockMovementModel
from src.ventas_pagos.web.schemas import POSSale

from tests.unit.reservas.test_create_reserva_idempotencia import make_world


def test_pos_sale_uses_server_price_stock_and_idempotency_key():
    db, world = make_world()
    actor, branch, variant = world["actor"], world["branch"], world["variant"]
    cash = OrganizationService(db).create_cash_point(
        CashPointCreate(branch_id=branch.id, code="CAJA-1", name="Caja principal"), actor
    )
    request = POSSale(
        client_request_id=uuid.uuid4(), branch_id=branch.id, cash_point_id=cash.id,
        customer_name="Consumidor final", payment_method="cash", payment_reference="REC-0001",
        payment_received=True, items=[{"variant_id": variant.id, "quantity": 2}],
    )
    first, replay = CommerceService(db).pos_sale(actor, request)
    again, replay_again = CommerceService(db).pos_sale(actor, request)
    stock = db.scalar(select(StockModel).where(StockModel.variant_id == variant.id, StockModel.branch_id == branch.id))
    movements = db.query(StockMovementModel).filter_by(variant_id=variant.id).all()

    assert not replay and replay_again and first.id == again.id
    assert first.status == "delivered" and first.payment_status == "paid"
    assert first.sales_channel == "pos" and first.total == 100
    assert stock.quantity == 18
    assert [(m.kind, m.delta, m.quantity_before, m.quantity_after) for m in movements] == [
        ("pos_sale", -2, 20, 18)
    ]


def test_stock_ledger_rejects_a_sale_when_units_are_not_available():
    db, world = make_world()
    actor, branch, variant = world["actor"], world["branch"], world["variant"]
    cash = OrganizationService(db).create_cash_point(CashPointCreate(branch_id=branch.id, code="CAJA-2", name="Caja dos"), actor)
    request = POSSale(client_request_id=uuid.uuid4(), branch_id=branch.id, cash_point_id=cash.id,
        customer_name="Cliente prueba", payment_method="cash", payment_reference="REC-0002", payment_received=True,
        items=[{"variant_id": variant.id, "quantity": 21}])
    from src.shared.exceptions.domain_exception import ConflictError
    import pytest
    with pytest.raises(ConflictError):
        CommerceService(db).pos_sale(actor, request)
    stock = db.scalar(select(StockModel).where(StockModel.variant_id == variant.id, StockModel.branch_id == branch.id))
    assert stock.quantity == 20
