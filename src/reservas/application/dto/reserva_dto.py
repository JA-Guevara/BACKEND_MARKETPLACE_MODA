from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReservaItemSnapshot:
    """Foto del producto/variante al momento de reservar, igual de espíritu que
    el snapshot de items que ventas_pagos guarda en cada pedido."""

    variant_id: str
    product_id: str
    name: str
    sku: str
    size: str
    color: str
    image_url: str | None
    quantity: int

    def as_dict(self) -> dict:
        return {
            "variant_id": self.variant_id,
            "product_id": self.product_id,
            "name": self.name,
            "sku": self.sku,
            "size": self.size,
            "color": self.color,
            "image_url": self.image_url,
            "quantity": self.quantity,
        }
