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


def set_rls_context(
    db: Session,
    tenant_id: UUID | str | None = None,
    is_platform: bool = False,
    access_context: Any = None,
) -> None:
    """Configura las variables de sesión PostgreSQL para Row Level Security por transacción.

    Usa SET LOCAL para que funcione de forma segura con poolers en modo transacción (PgBouncer/Supabase).
    """
    if access_context is not None:
        tenant_id = getattr(access_context, "tenant_id", None)
        is_platform = getattr(access_context, "is_platform", False)

    dialect_name = getattr(getattr(db.bind, "dialect", None), "name", "")
    if dialect_name != "postgresql":
        return

    try:
        if is_platform:
            db.execute(text("SET LOCAL app.platform = '1'"))
            db.execute(text("SET LOCAL app.tenant_id = ''"))
        elif tenant_id:
            db.execute(
                text("SET LOCAL app.tenant_id = :tenant"),
                {"tenant": str(tenant_id)},
            )
            db.execute(text("SET LOCAL app.platform = '0'"))
        else:
            db.execute(text("SET LOCAL app.tenant_id = ''"))
            db.execute(text("SET LOCAL app.platform = '0'"))
    except Exception:
        pass


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
    if not is_rls_enabled():
        return
    if getattr(connection.dialect, "name", "") != "postgresql":
        return
    try:
        from src.shared.context.audit_context import get_audit_scope
        tenant_id, _ = get_audit_scope()
        if tenant_id:
            connection.execute(
                text("SET LOCAL app.tenant_id = :tenant"),
                {"tenant": str(tenant_id)},
            )
            connection.execute(text("SET LOCAL app.platform = '0'"))
    except Exception:
        pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        if is_rls_enabled():
            try:
                from src.shared.context.audit_context import get_audit_scope
                tenant_id, _ = get_audit_scope()
                if tenant_id:
                    set_rls_context(db, tenant_id=tenant_id)
            except Exception:
                pass
        yield db
    finally:
        db.close()
