import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def test_database_connection():
    # La suite unitaria fuerza un motor inaccesible para no usar el .env.
    # Esta comprobación real exige una conexión local elegida por separado.
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requiere TEST_DATABASE_URL de un PostgreSQL local")
    if make_url(url).host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("TEST_DATABASE_URL debe apuntar a PostgreSQL local")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    except Exception as error:
        raise AssertionError(
            "No se pudo conectar a la base de datos. "
            "Verifica TEST_DATABASE_URL y que PostgreSQL local este ejecutandose."
        ) from error
    finally:
        engine.dispose()
