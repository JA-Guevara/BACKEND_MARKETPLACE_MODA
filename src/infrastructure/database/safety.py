"""Las herramientas locales no deben alcanzar una base remota por accidente."""
import os

from sqlalchemy.engine import URL, make_url


def require_local_database(database_url: str | URL) -> None:
    """Rechaza conexiones remotas salvo autorización explícita del entorno.

    No incluir la URL en el error: puede contener una contraseña. No se aceptan
    nombres DNS arbitrarios, aunque resuelvan a una IP de la red privada.
    """
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        return
    if url.get_backend_name() == "postgresql" and (
        (url.host or "").lower() in {"localhost", "127.0.0.1", "::1"}
    ) and not any(key in url.query for key in ("host", "hostaddr", "service")) and not (
        os.environ.get("PGHOSTADDR") or os.environ.get("PGSERVICE")
    ):
        return
    if os.environ.get("ALLOW_REMOTE_DB") == "1":
        return
    raise RuntimeError(
        "Conexión remota bloqueada. Use una base local. Para una operación "
        "remota autorizada, defina ALLOW_REMOTE_DB=1 en su entorno de ejecución."
    )
