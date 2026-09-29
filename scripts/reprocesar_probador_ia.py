"""Script para reprocesar en lote las prendas existentes con IA para el probador virtual.

Recorre todas las prendas del catálogo que tienen imagen, ejecuta el pipeline
mejorado de segmentación y anclajes semánticos, y actualiza los registros
en la tabla virtual_tryon_assets.
"""
import argparse
import sys
import uuid
from pathlib import Path

raiz = Path(__file__).resolve().parent.parent
if str(raiz) not in sys.path:
    sys.path.insert(0, str(raiz))

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import SessionLocal
from src.probador_virtual.application.use_cases.preparar_prenda import PrepararPrenda
from src.probador_virtual.infrastructure.persistence.models.recurso_tryon import (
    ESTADO_LISTO,
    ESTADO_MANUAL,
    TryOnAssetModel,
)
from src.usuarios_catalogo.infrastructure.models.catalog import ProductModel


def main():
    parser = argparse.ArgumentParser(
        description="Reprocesa recursos del probador con IA para prendas existentes."
    )
    parser.add_argument(
        "--product-id",
        type=str,
        default=None,
        help="UUID del producto específico a procesar (opcional).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Fuerza el reprocesamiento incluso si el recurso ya está marcado como listo.",
    )
    parser.add_argument(
        "--only-failed",
        action="store_true",
        help="Procesa únicamente los recursos que fallaron anteriormente.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        actor = (
            db.query(UserModel)
            .filter(UserModel.is_superuser.is_(True))
            .first()
            or db.query(UserModel).first()
        )
        if not actor:
            print("ERROR: No se encontró ningún usuario en la base de datos para auditoría.")
            sys.exit(1)

        print(f"Actor asignado para la preparación: {actor.email} (ID: {actor.id})")

        consulta = db.query(ProductModel).filter(
            ProductModel.deleted_at.is_(None),
            ProductModel.is_active.is_(True),
        )

        if args.product_id:
            try:
                pid = uuid.UUID(args.product_id)
                consulta = consulta.filter(ProductModel.id == pid)
            except ValueError:
                print(f"ERROR: product-id inválido: {args.product_id}")
                sys.exit(1)

        productos = consulta.all()
        print(f"Prendas encontradas en el catálogo: {len(productos)}")

        procesador = PrepararPrenda(db)
        total_procesados = 0
        total_listos = 0
        total_revision = 0
        total_fallidos = 0
        omitidos = 0

        for idx, prod in enumerate(productos, start=1):
            if not prod.images:
                print(f"[{idx}/{len(productos)}] OMITIDO: '{prod.name}' no tiene imágenes cargadas.")
                omitidos += 1
                continue

            colores = [v.color for v in prod.variants if v.is_active and v.color]
            colores_unicos = list({c.id: c for c in colores}.values())
            if not colores_unicos and prod.variants:
                colores_unicos = [v.color for v in prod.variants if v.color][:1]

            if not colores_unicos:
                print(f"[{idx}/{len(productos)}] OMITIDO: '{prod.name}' no tiene variantes con color asignado.")
                omitidos += 1
                continue

            for color in colores_unicos:
                existente = (
                    db.query(TryOnAssetModel)
                    .filter(
                        TryOnAssetModel.product_id == prod.id,
                        TryOnAssetModel.color_id == color.id,
                    )
                    .first()
                )

                if existente and not args.all:
                    if args.only_failed and existente.ai_status != "failed":
                        continue
                    if not args.only_failed and existente.ai_status in (ESTADO_LISTO, ESTADO_MANUAL):
                        print(
                            f"[{idx}/{len(productos)}] YA LISTO: '{prod.name}' (Color: {color.name}) - omitiendo."
                        )
                        total_listos += 1
                        continue

                print(
                    f"[{idx}/{len(productos)}] PROCESANDO CON IA: '{prod.name}' (Color: {color.name})..."
                )
                try:
                    recurso = procesador.execute(prod.id, color.id, actor)
                    total_procesados += 1
                    if recurso.ai_status == ESTADO_LISTO:
                        total_listos += 1
                        simbolo = "✓ LISTO"
                    elif recurso.ai_status == "review":
                        total_revision += 1
                        simbolo = "⚠ REVISIÓN"
                    else:
                        total_fallidos += 1
                        simbolo = "✗ FALLÓ"

                    print(
                        f"   ↳ {simbolo}: Calidad {recurso.quality_score}/100 | "
                        f"Región: {recurso.body_region} | Tipo: {recurso.garment_type} | "
                        f"Método: {recurso.ai_metadata.get('segmentation', 'n/a')}"
                    )
                except Exception as e:
                    total_fallidos += 1
                    print(f"   ↳ ERROR inesperado: {e}")

        print("\n" + "=" * 60)
        print("RESUMEN DE REPROCESAMIENTO IA PARA EL PROBADOR:")
        print(f"  Total procesados: {total_procesados}")
        print(f"  Listos para uso directo: {total_listos}")
        print(f"  En espera de revisión:  {total_revision}")
        print(f"  Fallidos:               {total_fallidos}")
        print(f"  Omitidos (sin fotos):   {omitidos}")
        print("=" * 60)
    finally:
        db.close()


if __name__ == "__main__":
    main()