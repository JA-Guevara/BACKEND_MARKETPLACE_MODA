"""Compara pg_dump --schema-only de dos bases locales, sin datos ni dueños."""

import re

from sqlalchemy.engine import URL

from scripts.respaldo.respaldar import conexion_pg, ejecutar


def _sentencias(dump: str) -> set[str]:
    # pg_dump separa cada objeto por su propio encabezado. Conservar el SQL
    # interno intacto evita alterar literales, defaults y cuerpos de funciones.
    lineas = []
    for linea in dump.splitlines():
        if linea.startswith("-- Name: "):
            lineas.append(None)
        elif not (linea.startswith("--") or linea.startswith("SET ")
                  or linea.startswith("SELECT pg_catalog.set_config(")
                  or re.match(r"^\\(?:un)?restrict(?:\s|$)", linea)):
            lineas.append(linea)

    objetos = set()
    fragmento: list[str] = []
    for linea in [*lineas, None]:
        if linea is not None:
            fragmento.append(linea)
            continue
        sentencia = "\n".join(fragmento).strip()
        fragmento = []
        if not sentencia:
            continue
        tabla = re.fullmatch(r"(CREATE TABLE [^\n]+ \()\n(.*)\n(\);)", sentencia, re.DOTALL)
        if tabla:
            columnas = re.split(r",\n(?=    \S)", tabla[2])
            sentencia = f"{tabla[1]}\n{',\n'.join(sorted(columnas))}\n{tabla[3]}"
        objetos.add(sentencia)
    return objetos


def _dump(url: str | URL) -> set[str]:
    _, env = conexion_pg(url, local=True)
    texto = ejecutar("pg_dump", ["--schema-only", "--no-owner", "--no-privileges", "-n", "public", "-w"],
                     env=env)
    return _sentencias(texto)


def comparar(url: str | URL, limpia: str | URL) -> list[str]:
    """Devuelve el SQL faltante o extra para diagnóstico local, sin registrarlo."""
    actual, esperado = _dump(url), _dump(limpia)
    return ([f"FALTA {objeto}" for objeto in sorted(esperado - actual)]
            + [f"EXTRA {objeto}" for objeto in sorted(actual - esperado)])
