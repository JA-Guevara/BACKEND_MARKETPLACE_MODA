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
    print("Preparando base de datos: alembic upgrade head", flush=True)
    # Si el pre-deploy ya migró, no hay cambios. Si falla, check=True impide
    # levantar una aplicación que consulta columnas/tablas aún inexistentes.
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    print("Migraciones completadas; iniciando servidor.", flush=True)
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "src.main:app",
                            "--host", "0.0.0.0", "--port", str(port),
                            "--workers", str(workers)])


if __name__ == "__main__":
    main()
