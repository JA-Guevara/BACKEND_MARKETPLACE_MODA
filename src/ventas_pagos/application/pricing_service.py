"""Servicio de cálculo y unificación de precios con ofertas (CU-11).

Es la ÚNICA fuente de la verdad para el precio vigente en tienda en línea,
caja (POS) y venta sin conexión (OFFLINE).
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.usuarios_catalogo.infrastructure.models.catalog import ProductVariantModel
from src.ventas_pagos.domain.promociones import mejor_automatica
from src.ventas_pagos.infrastructure.engagement_models import PromotionModel

CENT = Decimal("0.01")


@dataclass(frozen=True)
class PrecioVigente:
    regular: Decimal
    final: Decimal
    offer_id: str | None
    offer_name: str | None
    offer_ends_at: datetime | None

    @property
    def has_offer(self) -> bool:
        return self.offer_id is not None and self.final < self.regular


class PricingService:
    def __init__(self, db: Session, tenant_id: uuid.UUID):
        self.db = db
        self.tenant_id = tenant_id
        self._promos: list[PromotionModel] | None = None

    def _get_active_promotions(self) -> list[PromotionModel]:
        if self._promos is None:
            # Revisa la caché del request si existe en db.info
            cache = getattr(self.db, "info", {}).get("pricing_active_promos")
            if cache is not None and cache.get("tenant_id") == self.tenant_id:
                self._promos = cache.get("promos", [])
            else:
                stmt = (
                    select(PromotionModel)
                    .where(
                        PromotionModel.tenant_id == self.tenant_id,
                        PromotionModel.is_active.is_(True),
                        PromotionModel.code.is_(None),  # Solo automáticas
                    )
                )
                self._promos = list(self.db.scalars(stmt).all())
                if hasattr(self.db, "info"):
                    self.db.info["pricing_active_promos"] = {
                        "tenant_id": self.tenant_id,
                        "promos": self._promos,
                    }
        return self._promos

    def precio(
        self,
        variant: ProductVariantModel,
        canal: Literal["ONLINE", "POS", "OFFLINE"] = "ONLINE",
        momento: datetime | None = None,
    ) -> PrecioVigente:
        if momento is None:
            momento = datetime.now(timezone.utc)
        if momento.tzinfo is None:
            momento = momento.replace(tzinfo=timezone.utc)

        # Precio regular
        reg = variant.price_override if variant.price_override is not None else getattr(variant.product, "base_price", Decimal(0))
        regular = Decimal(str(reg)).quantize(CENT)

        promos = self._get_active_promotions()
        mejor = mejor_automatica(promos, variant, canal=canal, ahora=momento)

        if mejor is not None:
            return PrecioVigente(
                regular=regular,
                final=mejor.final_price,
                offer_id=mejor.promotion_id,
                offer_name=mejor.name,
                offer_ends_at=mejor.ends_at,
            )

        return PrecioVigente(
            regular=regular,
            final=regular,
            offer_id=None,
            offer_name=None,
            offer_ends_at=None,
        )

    def precios(
        self,
        variants: list[ProductVariantModel],
        canal: Literal["ONLINE", "POS", "OFFLINE"] = "ONLINE",
        momento: datetime | None = None,
    ) -> dict[uuid.UUID, PrecioVigente]:
        """Calcula los precios de un listado de variantes en memoria sin consultas extra."""
        res: dict[uuid.UUID, PrecioVigente] = {}
        for v in variants:
            res[v.id] = self.precio(v, canal=canal, momento=momento)
        return res
