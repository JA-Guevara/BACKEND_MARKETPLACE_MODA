"""Ajustes comunes a toda la suite.

La cola de correos está encendida por defecto en producción, pero en pruebas
tiene que estar apagada, y no es solo por comodidad:

* Las pruebas comprueban el booleano que devuelve `EnviarCorreo.execute` y el
  evento de bitácora en LA MISMA Session, justo después de llamar. Con el envío
  diferido ninguna de las dos cosas se cumple todavía cuando corre el `assert`.
* Los hilos de la cola abren su propia Session con `SessionLocal`, que apunta a
  `DATABASE_URL`. Las pruebas unitarias trabajan con su propio SQLite en memoria
  y nunca pasan por ahí: si un hilo enviara de verdad, escribiría eventos
  `notificaciones.email_*` en la base REAL, con actores que solo existen en el
  SQLite de la prueba.

Las pruebas que sí ejercitan la cola la encienden ellas mismas dentro del test,
con su propia instancia de `ColaDeCorreos` y su propia fábrica de Session.
"""
import pytest

from src.infrastructure.config.settings import settings

settings.email_background = False


@pytest.fixture(autouse=True)
def correo_en_linea():
    """Cada prueba arranca con el envío en línea, pase lo que pase en la anterior."""
    anterior = settings.email_background
    settings.email_background = False
    yield
    settings.email_background = anterior
