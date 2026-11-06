from collections.abc import Generator
import os
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from src.infrastructure.config.settings import settings
from src.infrastructure.database.safety import require_environment_match, require_local_database


def is_rls_enabled() -> bool:
    """Indica si Row Level Security (RLS) está activo según la variable de entorno."""
    return os.getenv("RLS_ENABLED", "false").lower() in ("1", "true", "yes")


def _write_rls_context(connection, tenant_id: str, platform: bool) -> None:
    # set_config(..., true) equivale a SET LOCAL y admite parámetros enlazados.
    connection.execute(text(
        "SELECT set_config('app.tenant_id', :tenant, true), "
        "set_config('app.platform', :platform, true)"
    ), {"tenant": tenant_id, "platform": "1" if platform else "0"})


def set_rls_context(
    db: Session, tenant_id=None, is_platform: bool = False, access_context=None,
) -> None:
    """Aplica el alcance validado ahora y en cada transacción de esta sesión.

    La empresa tiene prioridad sobre plataforma: una sesión delegada no obtiene
    acceso global. No se ignoran errores al fijar el contexto de PostgreSQL.
    """
    from uuid import UUID
    from src.shared.context.audit_context import set_database_scope
    if access_context is not None:
        tenant_id = access_context.tenant_id
        is_platform = access_context.is_platform
    tenant = UUID(str(tenant_id)) if tenant_id is not None else None
    platform = bool(is_platform) and tenant is None
    db.info["rls_scope"] = (str(tenant) if tenant else "", platform)
    set_database_scope(tenant, platform)
    if db.get_bind().dialect.name == "postgresql":
        _write_rls_context(db, str(tenant) if tenant else "", platform)


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


require_environment_match(settings.app_env, settings.database_url, settings.production_db_host)
require_local_database(settings.database_url)
engine = create_engine(settings.database_url, pool_pre_ping=True, **opciones_de_pool(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Session, "after_begin")
def _apply_rls_after_begin(session: Session, transaction: Any, connection: Any) -> None:
    if connection.dialect.name != "postgresql":
        return
    from src.shared.context.audit_context import get_database_scope
    scope = get_database_scope()
    if scope is None:
        tenant, platform = session.info.get("rls_scope", ("", False))
    else:
        tenant, platform = scope
    _write_rls_context(connection, str(tenant) if tenant else "", bool(platform) and not tenant)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
