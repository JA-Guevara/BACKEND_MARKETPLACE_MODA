"""Auditoría de solo lectura: imprime conteos, nunca filas ni conexiones."""
import argparse
import json
import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from src.infrastructure.database.safety import require_local_database


TABLES = ("products", "commerce_orders", "reservations")


def audit(database_url: str) -> dict:
    require_local_database(database_url)
    if make_url(database_url).get_backend_name() != "postgresql":
        raise RuntimeError("La auditoría requiere PostgreSQL.")
    engine = create_engine(database_url, isolation_level="REPEATABLE READ")
    try:
        with engine.connect() as db, db.begin():
            db.execute(text("SET TRANSACTION READ ONLY"))
            bypass = bool(db.scalar(text(
                "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname=current_user"
            )))
            result = {"rol_bypassrls": bypass, "tablas": {}, "auditoria_completa": True}
            for table in TABLES:
                role = db.execute(text(
                    "SELECT relrowsecurity, relforcerowsecurity, "
                    "pg_get_userbyid(relowner)=current_user AS owner "
                    "FROM pg_class WHERE oid=to_regclass(:name)"
                ), {"name": "public." + table}).one_or_none()
                if role is None:
                    result["tablas"][table] = {"existe": False}
                    result["auditoria_completa"] = False
                    continue
                owner = bool(role.owner)
                visible = bypass or not role.relrowsecurity or (owner and not role.relforcerowsecurity)
                entry = {"existe": True, "dueno": owner, "rls": bool(role.relrowsecurity),
                         "force_rls": bool(role.relforcerowsecurity), "alcance_completo": visible}
                if visible:
                    counts = db.execute(text(
                        f"SELECT COUNT(*) AS total, "
                        f"COUNT(*) FILTER (WHERE tenant_id IS NULL) AS sin_empresa, "
                        f"COUNT(*) FILTER (WHERE tenant_id IS NOT NULL AND NOT EXISTS "
                        f"(SELECT 1 FROM public.tenants t WHERE t.id=x.tenant_id)) AS huerfanas "
                        f"FROM public.{table} x"
                    )).one()
                    entry.update(total=counts.total, sin_empresa=counts.sin_empresa, huerfanas=counts.huerfanas)
                else:
                    # Cero filas bajo RLS no demuestra que no existan huérfanas.
                    result["auditoria_completa"] = False
                result["tablas"][table] = entry
            return result
    finally:
        engine.dispose()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-env", default="DATABASE_URL", help="Nombre de variable, nunca la URL")
    args = parser.parse_args(argv)
    value = os.getenv(args.database_env)
    if not value:
        print(json.dumps({"ok": False, "code": "database_env_missing"}))
        return 2
    try:
        result = audit(value)
    except (SQLAlchemyError, RuntimeError, ValueError):
        # Las excepciones de libpq pueden contener credenciales o datos SQL.
        print(json.dumps({"ok": False, "code": "tenant_audit_failed"}))
        return 1
    safe = result["auditoria_completa"] and all(
        row.get("sin_empresa", 0) == 0 and row.get("huerfanas", 0) == 0
        for row in result["tablas"].values()
    )
    print(json.dumps({"ok": safe, **result}, ensure_ascii=False))
    return 0 if safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
