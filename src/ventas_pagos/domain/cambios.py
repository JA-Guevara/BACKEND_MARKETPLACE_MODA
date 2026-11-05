from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from src.shared.exceptions.base_exception import AppException
from src.shared.exceptions.domain_exception import ValidationError


class ExchangeExpiredError(AppException):
    status_code = 400
    code = "exchange_expired"

    def __init__(self, dias_transcurridos: int, dias_permitidos: int):
        super().__init__(
            f"El plazo de cambio ha vencido. Transcurrieron {dias_transcurridos} días de los {dias_permitidos} permitidos.",
            code="exchange_expired",
            details={
                "dias_transcurridos": dias_transcurridos,
                "dias_permitidos": dias_permitidos,
            },
        )


class ExchangeItemUnavailableError(AppException):
    status_code = 409
    code = "exchange_stock_unavailable"

    def __init__(self, variant_id: str, disponible: int, solicitado: int):
        super().__init__(
            f"Existencias insuficientes para la prenda de cambio. Disponible: {disponible}, Solicitado: {solicitado}.",
            code="exchange_stock_unavailable",
            details={"variant_id": variant_id, "disponible": disponible, "solicitado": solicitado},
        )


class ExchangeQuantityExceededError(AppException):
    status_code = 400
    code = "exchange_quantity_exceeded"

    def __init__(self, variant_id: str, max_cambiable: int, solicitado: int):
        super().__init__(
            f"La cantidad a cambiar ({solicitado}) excede el máximo permitido ({max_cambiable}) para esta prenda.",
            code="exchange_quantity_exceeded",
            details={"variant_id": variant_id, "max_cambiable": max_cambiable, "solicitado": solicitado},
        )


@dataclass(frozen=True)
class LineaCambioCalculo:
    original_variant_id: UUID
    returned_quantity: int
    original_unit_price: Decimal
    new_variant_id: UUID
    delivered_quantity: int
    new_unit_price: Decimal

    @property
    def returned_value(self) -> Decimal:
        return self.original_unit_price * self.returned_quantity

    @property
    def delivered_value(self) -> Decimal:
        return self.new_unit_price * self.delivered_quantity

    @property
    def difference(self) -> Decimal:
        return self.delivered_value - self.returned_value


@dataclass(frozen=True)
class ResultadoCalculoCambio:
    total_returned_value: Decimal
    total_delivered_value: Decimal
    difference_amount: Decimal
    tipo_diferencia: Literal["PAGO_CLIENTE", "REINTEGRO_O_SALDO", "CAMBIO_DIRECTO"]
    lineas: List[LineaCambioCalculo]


class CalculadoraCambio:
    @staticmethod
    def calcular(lineas: List[LineaCambioCalculo]) -> ResultadoCalculoCambio:
        if not lineas:
            raise ValidationError("Debe especificar al menos una línea de cambio.")

        total_returned = sum((l.returned_value for l in lineas), Decimal("0.00"))
        total_delivered = sum((l.delivered_value for l in lineas), Decimal("0.00"))
        diff = total_delivered - total_returned

        if diff > Decimal("0.00"):
            tipo = "PAGO_CLIENTE"
        elif diff < Decimal("0.00"):
            tipo = "REINTEGRO_O_SALDO"
        else:
            tipo = "CAMBIO_DIRECTO"

        return ResultadoCalculoCambio(
            total_returned_value=total_returned,
            total_delivered_value=total_delivered,
            difference_amount=diff,
            tipo_diferencia=tipo,
            lineas=lineas,
        )


class VerificadorPlazoCambio:
    @staticmethod
    def verificar(fecha_compra: datetime, dias_permitidos: int, ahora: Optional[datetime] = None) -> int:
        """Verifica que la compra esté dentro del plazo y devuelve los días restantes."""
        ahora = ahora or datetime.now(timezone.utc)
        if fecha_compra.tzinfo is None:
            fecha_compra = fecha_compra.replace(tzinfo=timezone.utc)

        dias_transcurridos = (ahora - fecha_compra).days
        if dias_transcurridos > dias_permitidos:
            raise ExchangeExpiredError(dias_transcurridos, dias_permitidos)

        dias_restantes = max(0, dias_permitidos - dias_transcurridos)
        return dias_restantes
