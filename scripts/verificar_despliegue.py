"""Humo autorizado: salud, revisión, cabeceras y cuota de un login sintético.

Las seis peticiones de login pueden escribir en bitácora. No ejecutar contra
producción sin la autorización de la ventana de liberación. No imprime cuerpos,
cabeceras de autorización ni errores de transporte que puedan incluir secretos.
"""
import argparse
import os
import re
import sys
from urllib.parse import urlsplit

import requests


LOGIN_HUMO = {"email": "humo-limite@example.com", "password": "no-es-una-cuenta"}


def check(name: str, fn) -> bool:
    try:
        ok = bool(fn())
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        ok = False
    print(f"{'✔' if ok else '✕'} {name}")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Origen de la API, sin /api/v1")
    parser.add_argument("--revision-esperada", required=True)
    parser.add_argument("--token-env", help="Nombre de variable con token de plataforma, nunca el token")
    args = parser.parse_args(argv)
    target = urlsplit(args.base_url)
    if (target.scheme not in {"http", "https"} or not target.hostname or target.username or target.password
            or target.query or target.fragment or target.path.rstrip('/') not in {"", "/"}):
        parser.error("--base-url debe ser un origen HTTP/HTTPS sin credenciales ni /api/v1")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", args.revision_esperada):
        parser.error("--revision-esperada no es un identificador Alembic válido")
    if args.token_env and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.token_env):
        parser.error("--token-env debe ser el nombre de una variable, no su valor")
    base = args.base_url.rstrip('/')
    results: list[bool] = []

    def headers_ok(response) -> bool:
        return (response.headers.get("X-App-Env") in {"local", "test", "staging", "production"}
                and response.headers.get("X-Content-Type-Options") == "nosniff")

    with requests.Session() as session:
        # Las credenciales solo se añaden a la petición opcional de estado.
        def health() -> bool:
            r = session.get(base + '/health', timeout=15, allow_redirects=False)
            return r.status_code == 200 and r.json().get('status') == 'ok' and headers_ok(r)

        def ready() -> bool:
            r = session.get(base + '/health/ready', timeout=15, allow_redirects=False)
            body = r.json()
            return (r.status_code == 200 and body.get('status') == 'ready'
                    and body.get('revision') == args.revision_esperada and bool(body.get('version')) and headers_ok(r))

        def login_limit() -> bool:
            for i in range(6):
                r = session.post(base + '/api/v1/auth/login', json=LOGIN_HUMO, timeout=15, allow_redirects=False)
                if not headers_ok(r):
                    return False
                if i < 5:
                    if r.status_code != 401:
                        return False
                else:
                    return (r.status_code == 429 and r.json().get('error', {}).get('code') == 'rate_limited'
                            and int(r.headers.get('Retry-After', '0')) > 0
                            and r.headers.get('X-RateLimit-Limit') == '5'
                            and r.headers.get('X-RateLimit-Remaining') == '0')
            return False

        results.append(check('Salud y cabeceras', health))
        results.append(check('Disponibilidad y revisión esperada', ready))
        # No generar intentos de login si no está lista la versión esperada.
        if all(results):
            results.append(check('Cuota de login sintético en el sexto intento', login_limit))
        if args.token_env:
            def ops() -> bool:
                token = os.environ.get(args.token_env)
                if not token:
                    return False
                r = session.get(base + '/api/v1/platform/ops/status', headers={'Authorization': 'Bearer ' + token},
                                timeout=15, allow_redirects=False)
                body = r.json()
                data = body.get('data')
                return (r.status_code == 200 and body.get('success') is True and headers_ok(r)
                        and isinstance(data, dict) and isinstance(data.get('config_checks'), list)
                        and all(isinstance(item, dict) and item.get('level') in {'warning', 'info'}
                                for item in data['config_checks']))
            results.append(check('Configuración de plataforma sin errores bloqueantes', ops))
    print(f"Comprobaciones aprobadas: {sum(results)}/{len(results)}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
