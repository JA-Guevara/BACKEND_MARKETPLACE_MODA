from datetime import date
from enum import StrEnum


class EstadoEmpresa(StrEnum):
    ACTIVA = "ACTIVA"
    INACTIVA = "INACTIVA"


class EstadoSuscripcion(StrEnum):
    ACTIVA = "ACTIVA"
    VENCIDA = "VENCIDA"
    SUSPENDIDA = "SUSPENDIDA"
    CANCELADA = "CANCELADA"


FUNCIONES = ("products", "sales", "reservations", "offline", "conventional_reports", "ai_reports", "ml_analytics")
LIMITES = ("max_active_branches",)


def estado_efectivo(estado: str, fin: date, hoy: date) -> EstadoSuscripcion:
    return EstadoSuscripcion.VENCIDA if estado == "ACTIVA" and fin < hoy else EstadoSuscripcion(estado)


def dias_restantes(fin: date, hoy: date) -> int:
    return max(0, (fin - hoy).days)


def puede_operar(estado: EstadoSuscripcion) -> bool:
    return estado == EstadoSuscripcion.ACTIVA
