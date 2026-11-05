from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
import pytest

from src.ventas_pagos.domain.cambios import (
    CalculadoraCambio,
    ExchangeExpiredError,
    LineaCambioCalculo,
    VerificadorPlazoCambio,
)


def test_calculadora_cambio_diferencia_positiva_cliente_paga():
    vid_orig = uuid4()
    vid_new = uuid4()
    linea = LineaCambioCalculo(
        original_variant_id=vid_orig,
        returned_quantity=1,
        original_unit_price=Decimal("100.00"),
        new_variant_id=vid_new,
        delivered_quantity=1,
        new_unit_price=Decimal("150.00"),
    )
    res = CalculadoraCambio.calcular([linea])
    assert res.total_returned_value == Decimal("100.00")
    assert res.total_delivered_value == Decimal("150.00")
    assert res.difference_amount == Decimal("50.00")
    assert res.tipo_diferencia == "PAGO_CLIENTE"


def test_calculadora_cambio_diferencia_negativa_reintegro():
    vid_orig = uuid4()
    vid_new = uuid4()
    linea = LineaCambioCalculo(
        original_variant_id=vid_orig,
        returned_quantity=1,
        original_unit_price=Decimal("180.00"),
        new_variant_id=vid_new,
        delivered_quantity=1,
        new_unit_price=Decimal("120.00"),
    )
    res = CalculadoraCambio.calcular([linea])
    assert res.difference_amount == Decimal("-60.00")
    assert res.tipo_diferencia == "REINTEGRO_O_SALDO"


def test_calculadora_cambio_directo():
    vid_orig = uuid4()
    vid_new = uuid4()
    linea = LineaCambioCalculo(
        original_variant_id=vid_orig,
        returned_quantity=2,
        original_unit_price=Decimal("80.00"),
        new_variant_id=vid_new,
        delivered_quantity=2,
        new_unit_price=Decimal("80.00"),
    )
    res = CalculadoraCambio.calcular([linea])
    assert res.difference_amount == Decimal("0.00")
    assert res.tipo_diferencia == "CAMBIO_DIRECTO"


def test_verificador_plazo_dentro_del_limite():
    ahora = datetime.now(timezone.utc)
    compra = ahora - timedelta(days=5)
    restantes = VerificadorPlazoCambio.verificar(compra, dias_permitidos=15, ahora=ahora)
    assert restantes == 10


def test_verificador_plazo_vencido_lanza_excepcion():
    ahora = datetime.now(timezone.utc)
    compra = ahora - timedelta(days=20)
    with pytest.raises(ExchangeExpiredError) as exc_info:
        VerificadorPlazoCambio.verificar(compra, dias_permitidos=15, ahora=ahora)
    assert exc_info.value.code == "exchange_expired"
    assert exc_info.value.status_code == 400
