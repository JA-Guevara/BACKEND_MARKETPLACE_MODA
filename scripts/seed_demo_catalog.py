"""Carga un catálogo de demostración: 10 prendas por tipo, con imagen y variantes.

Escribe en la base configurada en `.env`. Registra todo lo que crea en
`scripts/demo_catalog_manifest.json`; `cleanup_demo_catalog.py` borra exactamente
esos registros y nada más. No modifica filas existentes.
"""
import json
import random
import sys
import unicodedata
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / 'scripts'))

from demo_images import generar  # noqa: E402
from src.infrastructure.database.session import SessionLocal  # noqa: E402
from src.inventario_sucursales.infrastructure.models.organization import BranchModel  # noqa: E402
from src.usuarios_catalogo.infrastructure.models.catalog import (  # noqa: E402
    CategoryModel,
    ColorModel,
    ProductImageModel,
    ProductModel,
    ProductVariantModel,
    SizeModel,
)
from src.ventas_pagos.infrastructure.models import StockModel  # noqa: E402

DESTINO_IMAGENES = RAIZ.parent / 'frontend_marketplace_moda' / 'public' / 'demo'
MANIFIESTO = RAIZ / 'scripts' / 'demo_catalog_manifest.json'
# Ruta relativa: la sirve el frontend en local y en el despliegue por igual.
BASE_PUBLICA = '/demo'

TALLAS = [
    ('XS', 'Extra pequeño', 1),
    ('S', 'Pequeño', 2),
    ('M', 'Mediano', 3),
    ('L', 'Grande', 4),
    ('XL', 'Extra grande', 5),
]
COLORES = [
    ('Negro', '#1F1F1F'),
    ('Blanco hueso', '#F2EFE8'),
    ('Gris melange', '#8A8A87'),
    ('Azul marino', '#1E2A44'),
    ('Celeste', '#7FA8C9'),
    ('Rojo tinto', '#8E2B33'),
    ('Verde oliva', '#5A6650'),
    ('Beige', '#D2BFA3'),
    ('Rosa palo', '#C98BA0'),
    ('Mostaza', '#C08A22'),
]
MARCAS = ['FashionStore Básicos', 'Nomad', 'Atelier SC', 'Línea Norte', 'Urbano']

TIPOS = {
    'poleras': ('Poleras', 'unisex', (89, 219), [
        'Polera básica de algodón', 'Polera oversize', 'Polera a rayas', 'Polera cuello V',
        'Polera premium peinada', 'Polera estampada', 'Polera deportiva',
        'Polera de algodón orgánico', 'Polera con bolsillo', 'Polera clásica']),
    'camisas': ('Camisas', 'hombre', (159, 389), [
        'Camisa de lino', 'Camisa Oxford', 'Camisa de denim', 'Camisa a cuadros',
        'Camisa manga larga', 'Camisa slim fit', 'Camisa casual', 'Camisa formal',
        'Camisa de rayas finas', 'Camisa de popelina']),
    'blusas': ('Blusas', 'mujer', (149, 359), [
        'Blusa de seda', 'Blusa con volados', 'Blusa satinada', 'Blusa cruzada',
        'Blusa de gasa', 'Blusa con lazo', 'Blusa escote V', 'Blusa manga globo',
        'Blusa plisada', 'Blusa estampada']),
    'pantalones': ('Pantalones', 'unisex', (199, 459), [
        'Pantalón chino', 'Jean recto', 'Jean skinny', 'Pantalón cargo',
        'Pantalón de vestir', 'Jogger de algodón', 'Pantalón wide leg',
        'Pantalón de corderoy', 'Pantalón de lino', 'Pantalón con pinzas']),
    'vestidos': ('Vestidos', 'mujer', (229, 549), [
        'Vestido midi', 'Vestido largo', 'Vestido camisero', 'Vestido ceñido',
        'Vestido de verano', 'Vestido de fiesta', 'Vestido casual', 'Vestido cruzado',
        'Vestido plisado', 'Vestido de tirantes']),
    'chaquetas': ('Chaquetas', 'unisex', (299, 699), [
        'Chaqueta de jean', 'Bomber clásica', 'Blazer entallado',
        'Chaqueta de cuero sintético', 'Parka impermeable', 'Rompevientos',
        'Chaqueta acolchada', 'Chaqueta oversize', 'Blazer de tweed',
        'Chaqueta universitaria']),
    'faldas': ('Faldas', 'mujer', (139, 329), [
        'Falda midi plisada', 'Falda lápiz', 'Falda de jean', 'Falda larga',
        'Falda cruzada', 'Falda tableada', 'Falda de cuero sintético', 'Falda evasé',
        'Falda corta', 'Falda satinada']),
    'shorts': ('Shorts', 'unisex', (99, 249), [
        'Short de jean', 'Short de lino', 'Short deportivo', 'Short cargo',
        'Short de tiro alto', 'Short de vestir', 'Short playero',
        'Bermuda de algodón', 'Short denim clásico', 'Short de algodón']),
}

DESCRIPCIONES = [
    'Corte cómodo para el uso diario, con terminaciones reforzadas y caída regular.',
    'Tejido suave y transpirable, pensado para acompañar toda la jornada sin perder forma.',
    'Prenda versátil que combina con básicos y con looks más armados.',
    'Confección cuidada, costuras planas y materiales de tacto liviano.',
    'Diseño atemporal que se adapta a distintas ocasiones sin esfuerzo.',
]


def slugify(texto: str) -> str:
    limpio = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode()
    return '-'.join(''.join(c if c.isalnum() else ' ' for c in limpio.lower()).split())


def obtener_o_crear(db, modelo, filtro: dict, valores: dict, creados: list):
    """Devuelve la fila existente o crea una nueva, anotándola para poder revertir."""
    existente = db.query(modelo).filter_by(**filtro).first()
    if existente:
        return existente, False
    fila = modelo(**{**filtro, **valores})
    db.add(fila)
    db.flush()
    creados.append(str(fila.id))
    return fila, True


def main() -> None:
    azar = random.Random(20260912)
    db = SessionLocal()
    manifiesto = {'categorias': [], 'tallas': [], 'colores': [], 'productos': [], 'imagenes': []}
    try:
        sucursales = db.query(BranchModel).filter(BranchModel.deleted_at.is_(None)).all()
        print(f'Sucursales encontradas: {len(sucursales)}')

        tallas = {}
        for codigo, nombre, orden in TALLAS:
            fila, nueva = obtener_o_crear(
                db, SizeModel, {'code': codigo},
                {'name': nombre, 'sort_order': orden, 'is_active': True},
                manifiesto['tallas'])
            tallas[codigo] = fila
            if nueva:
                print(f'  talla creada: {codigo}')

        colores = {}
        for nombre, hexa in COLORES:
            fila, nueva = obtener_o_crear(
                db, ColorModel, {'name': nombre},
                {'hex_code': hexa, 'is_active': True},
                manifiesto['colores'])
            colores[nombre] = fila
            if nueva:
                print(f'  color creado: {nombre}')

        total = 0
        for tipo, (titulo, genero, (minimo, maximo), nombres) in TIPOS.items():
            categoria, nueva = obtener_o_crear(
                db, CategoryModel, {'slug': slugify(titulo)},
                {'name': titulo,
                 'description': f'Prendas de la línea {titulo.lower()}.',
                 'is_active': True},
                manifiesto['categorias'])
            if nueva:
                print(f'Categoría creada: {titulo}')

            for indice, nombre in enumerate(nombres, start=1):
                slug = f'{slugify(nombre)}-{indice:02d}'
                if db.query(ProductModel).filter_by(slug=slug).first():
                    print(f'  omitida (ya existe): {slug}')
                    continue
                nombre_color, hexa = COLORES[(indice + len(tipo)) % len(COLORES)]
                precio = Decimal(azar.randrange(minimo, maximo, 10))
                producto = ProductModel(
                    name=nombre,
                    slug=slug,
                    description=f'{nombre}. {azar.choice(DESCRIPCIONES)}',
                    brand=MARCAS[indice % len(MARCAS)],
                    gender=genero,
                    base_price=precio,
                    category_id=categoria.id,
                    is_featured=indice <= 2,
                    is_active=True,
                )
                db.add(producto)
                db.flush()
                manifiesto['productos'].append(str(producto.id))

                archivo = DESTINO_IMAGENES / f'{slug}.webp'
                generar(tipo, hexa, archivo)
                manifiesto['imagenes'].append(archivo.name)
                db.add(ProductImageModel(
                    product_id=producto.id,
                    url=f'{BASE_PUBLICA}/{archivo.name}',
                    alt_text=f'{nombre} en {nombre_color.lower()}',
                    sort_order=0,
                    is_primary=True,
                ))

                for codigo_talla in ('S', 'M', 'L', 'XL'):
                    variante = ProductVariantModel(
                        product_id=producto.id,
                        size_id=tallas[codigo_talla].id,
                        color_id=colores[nombre_color].id,
                        sku=f'{tipo[:3].upper()}-{indice:02d}-{codigo_talla}',
                        is_active=True,
                    )
                    db.add(variante)
                    db.flush()
                    for sucursal in sucursales:
                        db.add(StockModel(
                            variant_id=variante.id,
                            branch_id=sucursal.id,
                            quantity=azar.randint(6, 24),
                        ))
                total += 1
            print(f'{titulo}: listo')

        MANIFIESTO.write_text(json.dumps(manifiesto, indent=1), encoding='utf-8')
        db.commit()
        print(f'\nProductos creados: {total}')
        print(f'Imágenes escritas en: {DESTINO_IMAGENES}')
        print(f'Manifiesto para revertir: {MANIFIESTO}')
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    main()
