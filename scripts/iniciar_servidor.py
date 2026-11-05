"""Arranque de producción: migrar antes de admitir peticiones o crear workers."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    try:
        port = int(os.getenv("PORT", "8000"))
        workers = int(os.getenv("WEB_CONCURRENCY", "1"))
    except ValueError:
        raise ValueError("config_invalid: PORT y WEB_CONCURRENCY deben ser números enteros.") from None
    if not 1 <= port <= 65535 or workers < 1:
        raise ValueError("config_invalid: PORT o WEB_CONCURRENCY fuera de rango.")
    from src.infrastructure.config.settings import settings
    if settings.rate_limit_enabled and workers > 1:
        raise RuntimeError("config_invalid: WEB_CONCURRENCY debe ser 1 con RATE_LIMIT_ENABLED; no se comparten cuotas entre workers.")
    forwarded = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1").strip() or "127.0.0.1"
    os.chdir(root)
    if os.environ.get("RAILWAY_ENVIRONMENT_ID"):
        # También protege los servicios que ejecutan el arranque directamente.
        from scripts.railway_entrypoint import preparar
        os.environ["ALLOW_REMOTE_DB"] = "1"
        print("Preparando base de datos en Railway (arranque compatible).", flush=True)
        preparar()
    else:
        print("Preparando base de datos: alembic upgrade head", flush=True)
        # Las herramientas locales conservan la guarda de acceso remoto.
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    print("Migraciones completadas; iniciando servidor.", flush=True)
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "src.main:app",
                            "--proxy-headers", "--forwarded-allow-ips", forwarded,
                            "--host", "0.0.0.0", "--port", str(port),
                            "--workers", str(workers)])


if __name__ == "__main__":
    main()
