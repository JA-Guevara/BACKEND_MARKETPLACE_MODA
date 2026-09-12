"""Revierte la carga de `seed_demo_catalog.py`.

Borra únicamente los identificadores anotados en `demo_catalog_manifest.json`, en
el orden que respeta las claves foráneas (stock, variantes, imágenes, productos y
después los maestros). Las categorías, tallas y colores solo se borran si ninguna
otra fila los usa. No toca nada que no esté en el manifiesto.

Uso:
    python scripts/cleanup_demo_catalog.py          # muestra qué borraría
    python scripts/cleanup_demo_catalog.py --aplicar
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src.infrastructure.database.session import SessionLocal  # noqa: E402
from src.usuarios_catalogo.infrastructure.models.catalog import (  # noqa: E402
    CategoryModel,
    ColorModel,
    ProductImageModel,
    ProductModel,
    ProductVariantModel,
    SizeModel,
)
from src.ventas_pagos.infrastructure.models import StockModel  # noqa: E402

MANIFIESTO = RAIZ / 'scripts' / 'demo_catalog_manifest.json'
DESTINO_IMAGENES = RAIZ.parent / 'frontend_marketplace_moda' / 'public' / 'demo'


def main() -> None:
    aplicar = '--aplicar' in sys.argv
    if not MANIFIESTO.exists():
        print(f'No hay manifiesto en {MANIFIESTO}: nada que revertir.')
        return
    datos = json.loads(MANIFIESTO.read_text(encoding='utf-8'))
    productos = datos.get('productos', [])
    db = SessionLocal()
    try:
        variantes = [
            str(v.id) for v in db.query(ProductVariantModel)
            .filter(ProductVariantModel.product_id.in_(productos)).all()
        ] if productos else []
        stock = db.query(StockModel).filter(StockModel.variant_id.in_(variantes)).count() if variantes else 0
        imagenes = db.query(ProductImageModel).filter(
            ProductImageModel.product_id.in_(productos)).count() if productos else 0

        print('Se eliminarían:')
        print(f'  filas de stock: {stock}')
        print(f'  variantes: {len(variantes)}')
        print(f'  imágenes (filas): {imagenes}')
        print(f'  productos: {len(productos)}')
        print(f'  categorías creadas: {len(datos.get("categorias", []))}')
        print(f'  tallas creadas: {len(datos.get("tallas", []))}')
        print(f'  colores creados: {len(datos.get("colores", []))}')
        print(f'  archivos de imagen: {len(datos.get("imagenes", []))}')

        if not aplicar:
            print('\nSimulación. Ejecutá con --aplicar para borrar de verdad.')
            return

        if variantes:
            db.query(StockModel).filter(StockModel.variant_id.in_(variantes)).delete(synchronize_session=False)
            db.query(ProductVariantModel).filter(
                ProductVariantModel.id.in_(variantes)).delete(synchronize_session=False)
        if productos:
            db.query(ProductImageModel).filter(
                ProductImageModel.product_id.in_(productos)).delete(synchronize_session=False)
            db.query(ProductModel).filter(ProductModel.id.in_(productos)).delete(synchronize_session=False)
        db.flush()

        # Los maestros se conservan si quedó alguna fila ajena usándolos.
        for ids, modelo, columna in (
            (datos.get('categorias', []), CategoryModel, ProductModel.category_id),
            (datos.get('tallas', []), SizeModel, ProductVariantModel.size_id),
            (datos.get('colores', []), ColorModel, ProductVariantModel.color_id),
        ):
            for identificador in ids:
                en_uso = db.query(columna).filter(columna == identificador).first()
                if en_uso:
                    print(f'  conservado (en uso): {modelo.__name__} {identificador}')
                    continue
                db.query(modelo).filter(modelo.id == identificador).delete(synchronize_session=False)
        db.commit()

        borrados = 0
        for nombre in datos.get('imagenes', []):
            archivo = DESTINO_IMAGENES / nombre
            if archivo.exists():
                archivo.unlink()
                borrados += 1
        MANIFIESTO.unlink()
        print(f'\nListo. Archivos de imagen borrados: {borrados}. Manifiesto eliminado.')
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    main()
