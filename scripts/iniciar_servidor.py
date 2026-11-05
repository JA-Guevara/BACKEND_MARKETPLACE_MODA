"""Arranque de producción: migrar antes de admitir peticiones o crear workers."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    port = int(os.getenv("PORT", "8000"))
    workers = int(os.getenv("WEB_CONCURRENCY", "2"))
    if not 1 <= port <= 65535 or workers < 1:
        raise ValueError("PORT o WEB_CONCURRENCY fuera de rango.")
    os.chdir(root)
    if os.environ.get("RAILWAY_ENVIRONMENT_ID"):
        # Compatibilidad con servicios que aún usan este comando directamente.
        # La autorización sin respaldo fue confirmada por el usuario el 05/11.
        # No depender del wrapper ni del proceso separado de pre-deploy para
        # habilitar el motor remoto y reparar el sello antiguo antes del upgrade.
        from scripts.railway_entrypoint import preparar
        os.environ["ALLOW_REMOTE_DB"] = "1"
        print("Preparando base de datos en Railway (arranque compatible).", flush=True)
        preparar(sin_respaldo=True)
    else:
        print("Preparando base de datos: alembic upgrade head", flush=True)
        # Las herramientas locales conservan la guarda de acceso remoto.
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    print("Migraciones completadas; iniciando servidor.", flush=True)
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "src.main:app",
                            "--host", "0.0.0.0", "--port", str(port),
                            "--workers", str(workers)])


if __name__ == "__main__":
    main()
