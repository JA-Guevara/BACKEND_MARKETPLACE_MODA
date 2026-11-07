"""Prepara o restablece los datos base de la empresa demo."""
import argparse

from src.infrastructure.database.session import SessionLocal, set_rls_context
from src.plataforma_saas.application.sandbox_seed import seed_demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Restaura el catálogo y las sucursales de prueba.")
    args = parser.parse_args()
    with SessionLocal.begin() as db:
        set_rls_context(db, is_platform=True)
        demo = seed_demo(db, reset=args.reset)
        print(f"Empresa demo lista: {demo.trade_name} (slug: {demo.slug})")


if __name__ == "__main__":
    main()
