from sqlalchemy import text

from src.infrastructure.database.session import engine


def test_database_connection():
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    except Exception as error:
        raise AssertionError(
            "No se pudo conectar a la base de datos. "
            "Verifica DATABASE_URL en el archivo .env y que PostgreSQL este ejecutandose."
        ) from error
