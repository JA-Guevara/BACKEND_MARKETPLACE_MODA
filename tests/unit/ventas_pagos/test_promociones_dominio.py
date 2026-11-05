"""Pruebas puras de dominio para promociones y ofertas (CU-11)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
import pytest

from src.ventas_pagos.domain.promociones import (
    alcanza,
    estado,
    mejor_automatica,
    precio_final,
    validar,
    vigente_en,
)


class DummyTarget:
    def __init__(self, target_type: str, target_id):
        self.target_type = target_type
        self.target_id = target_id


class DummyProduct:
    def __init__(self, id, base_price, category_id=None, season_id=None, collection_id=None):
        self.id = id
        self.base_price = Decimal(str(base_price))
        self.category_id = category_id
        self.season_id = season_id
        self.collection_id = collection_id


class DummyVariant:
    def __init__(self, id, product, price_override=None):
        self.id = id
        self.product_id = product.id
        self.product = product
        self.price_override = Decimal(str(price_override)) if price_override is not None else None


class DummyPromotion:
    def __init__(
        self,
        id=None,
        name="Promo test",
        code=None,
        discount_type="percent",
        discount_value=Decimal("20.00"),
        is_active=True,
        starts_at=None,
        ends_at=None,
        deactivated_at=None,
        max_uses=None,
        uses_count=0,
        applies_online=True,
        applies_pos=True,
        applies_offline=False,
        targets=None,
        category_id=None,
        product_id=None,
    ):
        self.id = id or uuid4()
        self.name = name
        self.code = code
        self.discount_type = discount_type
        self.discount_value = Decimal(str(discount_value))
        self.is_active = is_active
        self.starts_at = starts_at
        self.ends_at = ends_at
        self.deactivated_at = deactivated_at
        self.max_uses = max_uses
        self.uses_count = uses_count
        self.applies_online = applies_online
        self.applies_pos = applies_pos
        self.applies_offline = applies_offline
        self.targets = targets or []
        self.category_id = category_id
        self.product_id = product_id


def test_precio_final_porcentual():
    assert precio_final(Decimal("100.00"), "percent", Decimal("20.00")) == Decimal("80.00")
    assert precio_final(Decimal("250.50"), "percent", Decimal("10.00")) == Decimal("225.45")


def test_precio_final_monto_fijo():
    assert precio_final(Decimal("100.00"), "fixed", Decimal("30.00")) == Decimal("70.00")
    assert precio_final(Decimal("25.00"), "fixed", Decimal("50.00")) == Decimal("0.00")


def test_precio_final_liquidacion():
    assert precio_final(Decimal("100.00"), "clearance", Decimal("49.90")) == Decimal("49.90")


def test_validar_reglas_basicas():
    # Descuento negativo
    errores = validar("percent", Decimal("-5"), None, None, [Decimal("100")])
    assert any("mayor a cero" in e for e in errores)

    # Porcentaje mayor a 90%
    errores = validar("percent", Decimal("95"), None, None, [Decimal("100")])
    assert any("90%" in e for e in errores)

    # Fechas invertidas
    ahora = datetime.now(timezone.utc)
    errores = validar("fixed", Decimal("10"), ahora, ahora - timedelta(days=1), [Decimal("100")])
    assert any("posterior" in e for e in errores)

    # Precio final <= 0
    errores = validar("fixed", Decimal("120"), None, None, [Decimal("100")])
    assert any("menor o igual a cero" in e for e in errores)


def test_vigente_en_y_estado():
    ahora = datetime.now(timezone.utc)
    ayer = ahora - timedelta(days=1)
    manana = ahora + timedelta(days=1)

    p_activa = DummyPromotion(starts_at=ayer, ends_at=manana)
    assert vigente_en(p_activa, ahora) is True
    assert estado(p_activa, ahora) == "ACTIVA"

    # Desactivada antes de ahora (3b)
    p_desactivada = DummyPromotion(starts_at=ayer, ends_at=manana, deactivated_at=ayer + timedelta(hours=2))
    assert vigente_en(p_desactivada, ahora) is False
    assert estado(p_desactivada, ahora) == "INACTIVA"

    # Programada para el futuro
    p_futura = DummyPromotion(starts_at=manana, ends_at=manana + timedelta(days=2))
    assert vigente_en(p_futura, ahora) is False
    assert estado(p_futura, ahora) == "PROGRAMADA"

    # Vencida
    p_vencida = DummyPromotion(starts_at=ayer - timedelta(days=5), ends_at=ayer)
    assert vigente_en(p_vencida, ahora) is False
    assert estado(p_vencida, ahora) == "VENCIDA"

    # Agotada por límite de usos
    p_agotada = DummyPromotion(starts_at=ayer, ends_at=manana, max_uses=10, uses_count=10)
    assert estado(p_agotada, ahora) == "AGOTADA"


def test_alcanza_por_variante_y_categoria():
    cat1 = uuid4()
    cat2 = uuid4()
    p1 = DummyProduct(uuid4(), Decimal("100.00"), category_id=cat1)
    v1 = DummyVariant(uuid4(), p1)

    # Oferta que alcanza categoría 1
    t_cat1 = DummyTarget("CATEGORY", cat1)
    promo = DummyPromotion(targets=[t_cat1])
    assert alcanza(promo, v1) is True

    # Oferta que alcanza categoría 2
    t_cat2 = DummyTarget("CATEGORY", cat2)
    promo2 = DummyPromotion(targets=[t_cat2])
    assert alcanza(promo2, v1) is False


def test_mejor_automatica_no_se_apilan_y_filtra_canal():
    ahora = datetime.now(timezone.utc)
    cat1 = uuid4()
    prod = DummyProduct(uuid4(), Decimal("100.00"), category_id=cat1)
    var = DummyVariant(uuid4(), prod)

    promo_10 = DummyPromotion(name="10% OFF", discount_type="percent", discount_value=Decimal("10"), applies_pos=True, applies_online=True)
    promo_30 = DummyPromotion(name="30% OFF", discount_type="percent", discount_value=Decimal("30"), applies_pos=True, applies_online=True)
    promo_pos_only = DummyPromotion(name="50% POS", discount_type="percent", discount_value=Decimal("50"), applies_pos=True, applies_online=False)

    # En ONLINE la de 50% no aplica, se elige 30%
    mejor_online = mejor_automatica([promo_10, promo_30, promo_pos_only], var, canal="ONLINE", ahora=ahora)
    assert mejor_online is not None
    assert mejor_online.name == "30% OFF"
    assert mejor_online.final_price == Decimal("70.00")

    # En POS la de 50% sí aplica y es la mejor
    mejor_pos = mejor_automatica([promo_10, promo_30, promo_pos_only], var, canal="POS", ahora=ahora)
    assert mejor_pos is not None
    assert mejor_pos.name == "50% POS"
    assert mejor_pos.final_price == Decimal("50.00")
