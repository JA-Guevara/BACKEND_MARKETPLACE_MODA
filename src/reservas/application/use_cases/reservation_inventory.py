"""Inventory released in the same transaction as reservation completion.

The caller must hold the reservation row lock and commit the whole operation.
Attending a fitting releases its hold; a purchase is a separate sale operation.
"""
from uuid import UUID

from sqlalchemy.orm import Session

from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.ventas_pagos.application.stock_service import StockService


def release_reservation_inventory(
    db: Session, reserva: ReservationModel, actor_id: UUID | None, reason: str,
) -> None:
    if not reserva.inventory_held:
        return
    inventory = StockService(db)
    for item in sorted(reserva.items, key=lambda item: str(item["variant_id"])):
        inventory.change(
            UUID(str(item["variant_id"])), reserva.branch_id, int(item["quantity"]),
            "reservation_release", reason, reference=str(reserva.id), actor_id=actor_id,
        )
    reserva.inventory_held = False
