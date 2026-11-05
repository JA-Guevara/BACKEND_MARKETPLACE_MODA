"""Las herramientas locales no deben alcanzar una base remota por accidente."""
import os
import re

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


def _parse_url(database_url: str | URL) -> URL:
    try:
        return make_url(database_url)
    except (ArgumentError, TypeError, ValueError):
        raise RuntimeError("DATABASE_URL no tiene un formato válido.") from None


def _overrides_host(url: URL) -> bool:
    return bool(
        any(key.lower() in {"host", "hostaddr", "service"} for key in url.query)
        or os.environ.get("PGHOSTADDR") or os.environ.get("PGSERVICE")
    )


def _is_local(url: URL) -> bool:
    return url.get_backend_name() == "sqlite" or (
        url.get_backend_name() == "postgresql"
        and (url.host or "").lower() in {"localhost", "127.0.0.1", "::1"}
        and not _overrides_host(url)
    )


def require_local_database(database_url: str | URL, *, allow_remote: bool = True) -> None:
    """Rechaza conexiones remotas salvo autorización explícita del entorno.

    No incluir la URL en el error: puede contener una contraseña. No se aceptan
    nombres DNS arbitrarios, aunque resuelvan a una IP de la red privada.
    """
    if _is_local(_parse_url(database_url)):
        return
    if allow_remote and os.environ.get("ALLOW_REMOTE_DB") == "1":
        return
    raise RuntimeError(
        "Conexión remota bloqueada. Use una base local. Para una operación "
        "remota autorizada, defina ALLOW_REMOTE_DB=1 en su entorno de ejecución."
    )


def _supabase_direct_ref(host: str) -> str | None:
    match = re.fullmatch(r"db\.([a-z0-9-]+)\.supabase\.co", host)
    return match.group(1) if match else None


def require_environment_match(
    app_env: str, database_url: str | URL, production_db_host: str | None = None
) -> None:
    """Comprueba el destino antes de construir un motor o ejecutar migraciones."""
    url = _parse_url(database_url)
    if app_env in {"local", "test"}:
        if not _is_local(url):
            raise RuntimeError(f"Conexión remota bloqueada para APP_ENV={app_env}. Requiere APP_ENV=production.")
        return
    if app_env == "production":
        if not os.environ.get("RAILWAY_ENVIRONMENT_ID", "").strip():
            raise RuntimeError("APP_ENV=production requiere RAILWAY_ENVIRONMENT_ID.")
        return
    if app_env != "staging":
        raise RuntimeError("APP_ENV no es un ambiente permitido.")
    production = (production_db_host or "").strip().lower().rstrip(".")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", production):
        raise RuntimeError("APP_ENV=staging requiere PRODUCTION_DB_HOST como nombre de host.")
    host = (url.host or "").lower().rstrip(".")
    if url.get_backend_name() != "postgresql" or not host or _overrides_host(url):
        raise RuntimeError("Staging requiere un destino PostgreSQL sin overrides de host.")
    if host == production:
        raise RuntimeError("Staging y producción no pueden usar el mismo host.")
    production_ref = _supabase_direct_ref(production)
    if host.endswith(".pooler.supabase.com"):
        # El host del pooler se comparte entre proyectos. Un dominio distinto
        # por sí solo no distingue la producción de un proyecto staging.
        role, separator, target_ref = (url.username or "").rpartition(".")
        if not production_ref or not separator or not role or not re.fullmatch(r"[a-z0-9-]+", target_ref):
            raise RuntimeError("Para un pooler de staging use el host directo canónico de producción en PRODUCTION_DB_HOST.")
        if target_ref == production_ref:
            raise RuntimeError("El pooler de staging apunta al proyecto de producción.")
