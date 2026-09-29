from sqlalchemy import create_engine

from src.infrastructure.config.settings import settings
from src.infrastructure.database import session as modulo_sesion
from src.infrastructure.database.session import SessionLocal, engine, opciones_de_pool


def test_postgres_recibe_el_pool_dimensionado():
    opciones = opciones_de_pool("postgresql://usuario:clave@servidor:5432/base")

    assert opciones == {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout,
        "pool_recycle": settings.db_pool_recycle,
    }


def test_el_total_de_conexiones_entra_en_el_plan_gratuito_de_supabase():
    # Supabase Nano admite 60 conexiones directas y su propia guia recomienda no
    # pasar del 40 % (24). Con 2 workers el total es 2 x (size + overflow): esta
    # prueba es el candado que impide subir el pool y quedarse sin conexiones.
    por_proceso = settings.db_pool_size + settings.db_max_overflow

    assert por_proceso * 2 <= 24


def test_sqlite_no_recibe_argumentos_de_queuepool():
    # max_overflow y pool_timeout solo existen en QueuePool: con SQLite en memoria
    # SQLAlchemy usa SingletonThreadPool y create_engine lanzaria TypeError. Como
    # el engine se construye al importar el modulo, ese fallo no romperia una
    # prueba sino la recoleccion completa de la suite.
    assert opciones_de_pool("sqlite+pysqlite:///:memory:") == {}

    motor = create_engine(
        "sqlite+pysqlite:///:memory:",
        pool_pre_ping=True,
        **opciones_de_pool("sqlite+pysqlite:///:memory:"),
    )
    motor.dispose()


def test_el_engine_del_modulo_conserva_pre_ping_y_reciclado():
    assert engine.pool._pre_ping is True
    if settings.database_url.startswith("postgresql"):
        assert engine.pool.size() == settings.db_pool_size
        assert engine.pool._max_overflow == settings.db_max_overflow
        assert engine.pool._recycle == settings.db_pool_recycle
        assert engine.pool._timeout == settings.db_pool_timeout


def test_los_simbolos_publicos_siguen_existiendo():
    # tests/integration/database/test_connection.py importa `engine` por nombre y
    # `SessionLocal` es API publica de hecho: renombrarlos rompe consumidores.
    assert modulo_sesion.engine is engine
    assert SessionLocal.kw["expire_on_commit"] is False
    assert SessionLocal.kw["autoflush"] is False


def test_la_cola_de_correos_tiene_ajustes_declarados():
    # La pista de notificaciones lee estos tres ajustes; quedan aqui para que el
    # envio diferido se pueda apagar por variable de entorno sin tocar codigo.
    assert isinstance(settings.email_background, bool)
    assert settings.email_queue_size > 0
    assert settings.email_workers >= 1
