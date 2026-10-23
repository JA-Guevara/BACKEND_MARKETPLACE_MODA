from datetime import date, timedelta
from src.plataforma_saas.domain.estados import EstadoSuscripcion, estado_efectivo, dias_restantes, puede_operar


def test_estados_y_vigencia():
    today = date.today()
    assert estado_efectivo("ACTIVA", today-timedelta(days=1), today) == EstadoSuscripcion.VENCIDA
    assert estado_efectivo("ACTIVA", today, today) == EstadoSuscripcion.ACTIVA
    assert estado_efectivo("SUSPENDIDA", today+timedelta(days=1), today) == EstadoSuscripcion.SUSPENDIDA
    assert dias_restantes(today+timedelta(days=6), today) == 6
    assert dias_restantes(today-timedelta(days=6), today) == 0
    assert not puede_operar(EstadoSuscripcion.VENCIDA)
    assert puede_operar(EstadoSuscripcion.ACTIVA)
