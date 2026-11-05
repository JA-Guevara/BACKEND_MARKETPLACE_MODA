"""Genera un pg_dump de public y un manifiesto sin credenciales."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class ErrorRespaldo(RuntimeError):
    """Mensaje seguro para el operador, sin salida de libpq ni datos de filas."""


def conexion_pg(url: str | URL, *, local: bool = False) -> tuple[URL, dict[str, str]]:
    """Entrega las credenciales exclusivamente por entorno del proceso hijo."""
    try:
        destino = make_url(url)
        puerto = destino.port or 5432
    except (ArgumentError, ValueError, TypeError):
        raise ErrorRespaldo("URL de PostgreSQL inválida.") from None

    host = destino.host or ""
    opciones = {"sslmode", "sslrootcert", "sslcert", "sslkey"}
    if (destino.get_backend_name() != "postgresql"
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", destino.database or "")
            or not re.fullmatch(r"[A-Za-z0-9.:-]+", host)
            or not 1 <= puerto <= 65535
            or not set(destino.query) <= opciones
            or any(not isinstance(valor, str) for valor in destino.query.values())):
        raise ErrorRespaldo("Se requiere un destino PostgreSQL explícito y sin redirecciones.")

    loopback = host.lower() in {"localhost", "127.0.0.1", "::1"}
    if local:
        from src.infrastructure.database.safety import require_local_database

        if not loopback:
            raise ErrorRespaldo("La restauración requiere PostgreSQL local.")
        try:
            require_local_database(destino)
        except RuntimeError:
            raise ErrorRespaldo("La conexión local está bloqueada por la configuración de libpq.") from None

    entorno_sistema = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "HOME", "USERPROFILE",
                      "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "LD_LIBRARY_PATH"}
    env = {nombre: valor for nombre, valor in os.environ.items() if nombre.upper() in entorno_sistema}
    env.update({"PGHOST": host, "PGPORT": str(puerto), "PGDATABASE": destino.database,
                "PGCONNECT_TIMEOUT": "15", "PGCLIENTENCODING": "UTF8"})
    if local:
        env["PGHOSTADDR"] = "127.0.0.1" if host.lower() == "localhost" else host
    if destino.username is not None:
        env["PGUSER"] = destino.username
    if destino.password is not None:
        env["PGPASSWORD"] = destino.password
    for nombre, valor in destino.query.items():
        env[f"PG{nombre.upper()}"] = valor
    if not loopback and env.setdefault("PGSSLMODE", "require") not in {"require", "verify-ca", "verify-full"}:
        raise ErrorRespaldo("La conexión de respaldo remota requiere TLS.")
    return destino, env


def ejecutar(herramienta: str, args: list[str], *, env: dict[str, str] | None = None,
             cwd: Path | None = None, timeout: int = 1800) -> str:
    try:
        proceso = subprocess.run([herramienta, *args], env=env, cwd=cwd, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise ErrorRespaldo(f"{Path(herramienta).name} no está disponible o agotó el tiempo de espera.") from None
    if proceso.returncode != 0:
        # Las herramientas pueden devolver errores con nombres de usuarios, filas o DSN.
        raise ErrorRespaldo(f"{Path(herramienta).name} falló (código {proceso.returncode}).")
    return proceso.stdout


def consulta(url: str | URL, sql: str, *, local: bool = False) -> str:
    _, env = conexion_pg(url, local=local)
    return ejecutar("psql", ["-X", "-A", "-t", "-w", "-v", "ON_ERROR_STOP=1", "-c", sql],
                    env=env, timeout=60).strip()


def version_servidor(url: str | URL) -> int:
    valor = consulta(url, "SHOW server_version_num")
    if not valor.isdigit():
        raise ErrorRespaldo("No se pudo identificar la versión del servidor PostgreSQL.")
    return int(valor)


def validar_version_dump(version: int) -> None:
    salida = ejecutar("pg_dump", ["--version"], timeout=15)
    mayor = re.search(r"\(PostgreSQL\)\s+(\d+)", salida)
    if not mayor:
        raise ErrorRespaldo("No se pudo identificar la versión de pg_dump.")
    if int(mayor.group(1)) < version // 10000:
        raise ErrorRespaldo("pg_dump es anterior a la versión mayor del servidor PostgreSQL.")


def validar_salida(directorio: str | Path) -> Path:
    ruta = Path(directorio).expanduser().resolve()
    for ancestro in (ruta, *ruta.parents):
        marca_git = ancestro / ".git"
        if (ancestro.name.casefold() == "primer examen parcial"
                or marca_git.exists() or marca_git.is_symlink()):
            raise ErrorRespaldo("La salida debe estar fuera de los repositorios y de Primer Examen Parcial.")
    return ruta


def ejecutar_dump(url: str | URL, destino: Path) -> Path:
    real = destino.resolve()
    validar_salida(real.parent)
    if real.exists():
        raise ErrorRespaldo("La salida de pg_dump ya existe.")
    _, env = conexion_pg(url)
    ejecutar("pg_dump", ["-Fc", "-n", "public", "--no-owner", "--no-privileges",
                         "-w", "-f", str(real)], env=env)
    if not destino.is_file() or not destino.stat().st_size:
        raise ErrorRespaldo("pg_dump no generó un archivo completo.")
    return destino


def revision_dump(archivo: Path) -> str:
    # La revisión sale del mismo snapshot que el dump, incluso si se despliega en paralelo.
    salida = ejecutar("pg_restore", ["--data-only", "--schema=public", "--table=alembic_version",
                                    "--no-owner", "--no-privileges", "--file=-", str(archivo)])
    filas = re.search(r"^COPY public\.alembic_version \(version_num\) FROM stdin;\n(.*?)^\\\.$",
                      salida, re.MULTILINE | re.DOTALL)
    revision = filas.group(1).strip() if filas else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", revision):
        raise ErrorRespaldo("La copia no contiene una única revisión Alembic válida.")
    return revision


def cifrar(path: Path, recipient: str) -> Path:
    if not re.fullmatch(r"age1[0-9a-z]+", recipient):
        raise ErrorRespaldo("El destinatario debe ser una clave pública age.")
    salida = path.with_suffix(path.suffix + ".age")
    ejecutar("age", ["-r", recipient, "-o", str(salida), str(path)])
    if not salida.is_file() or not salida.stat().st_size:
        raise ErrorRespaldo("age no generó un archivo completo.")
    path.unlink()
    return salida


def manifiesto(path: Path, meta: dict) -> dict:
    with path.open("rb") as archivo:
        huella = hashlib.file_digest(archivo, "sha256").hexdigest()
    return {"archivo": path.name, "bytes": path.stat().st_size, "sha256": huella,
            **{clave: meta[clave] for clave in ("tipo", "inicio", "fin", "revision_alembic",
                                               "version_servidor", "host_redactado")}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--salida", type=Path, required=True)
    parser.add_argument("--tipo", choices=("daily", "weekly", "pre_migration", "manual"), required=True)
    parser.add_argument("--age-recipient")
    parser.add_argument("--env-var", default="BACKUP_DATABASE_URL")
    args = parser.parse_args(argv)

    try:
        salida = validar_salida(args.salida)
        url = os.environ.get(args.env_var)
        if not url:
            raise ErrorRespaldo("Falta la conexión en la variable de entorno indicada.")
        destino, _ = conexion_pg(url)
        inicio = datetime.now(timezone.utc)
        version = version_servidor(destino)
        validar_version_dump(version)
        salida.mkdir(parents=True, exist_ok=True, mode=0o700)
        nombre = f"bd-{inicio:%Y%m%dT%H%M%SZ}-{args.tipo}-{uuid4().hex[:8]}"

        with tempfile.TemporaryDirectory(prefix=".respaldo-", dir=salida) as temporal:
            carpeta = Path(temporal)
            archivo = ejecutar_dump(destino, carpeta / f"{nombre}.dump")
            revision = revision_dump(archivo)
            if args.age_recipient:
                archivo = cifrar(archivo, args.age_recipient)
            meta = manifiesto(archivo, {"tipo": args.tipo, "inicio": inicio.isoformat(),
                "fin": datetime.now(timezone.utc).isoformat(), "revision_alembic": revision,
                "version_servidor": version, "host_redactado": destino.host})
            registro = carpeta / f"{nombre}.manifest.json"
            registro.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            publicado = salida / archivo.name
            archivo.replace(publicado)
            try:
                registro.replace(salida / registro.name)
            except OSError:
                publicado.unlink(missing_ok=True)
                raise
        print(f"Copia generada con manifiesto {registro.name}.")
        return 0
    except ErrorRespaldo as error:
        print(error)
    except OSError:
        print("No se pudo guardar la copia o el manifiesto.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
