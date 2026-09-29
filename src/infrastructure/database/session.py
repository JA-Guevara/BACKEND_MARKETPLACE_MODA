from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.infrastructure.config.settings import settings


def opciones_de_pool(database_url: str) -> dict[str, Any]:
    """Argumentos de pool que acepta el motor de esta URL.

    `max_overflow` y `pool_timeout` pertenecen a QueuePool: pasarselos al
    SingletonThreadPool que SQLAlchemy elige para `sqlite+pysqlite:///:memory:`
    levanta TypeError. Y como `create_engine` corre al importar este modulo —que
    casi toda la suite arrastra via `src.main`—, ese TypeError no tumbaria una
    prueba sino la recoleccion entera. Por eso el ajuste del pool se aplica solo
    cuando la URL es PostgreSQL, que es el unico motor donde hace falta.
    """
    if not database_url.startswith("postgresql"):
        return {}
    return {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout,
        # Supabase cierra las conexiones ociosas: sin reciclado, la primera
        # peticion tras un rato de calma paga el reintento de pool_pre_ping.
        "pool_recycle": settings.db_pool_recycle,
    }


engine = create_engine(settings.database_url, pool_pre_ping=True, **opciones_de_pool(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
