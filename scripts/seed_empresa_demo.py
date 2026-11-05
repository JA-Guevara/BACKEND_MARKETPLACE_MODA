"""
Sembrador idempotente de la empresa demo (sandbox) para pruebas de la plataforma SaaS.
Solo afecta a empresas marcadas con is_sandbox = True.
Uso: python -m scripts.seed_empresa_demo [--reset]
"""

import argparse
import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.infrastructure.database.session import SessionLocal
from src.inventario_sucursales.infrastructure.models.organization import (
    BranchModel,
    CashPointModel,
    CityModel,
)
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.usuarios_catalogo.infrastructure.models.catalog import (
    CategoryModel,
    ColorModel,
    ProductImageModel,
    ProductModel,
    ProductVariantModel,
    SizeModel,
)


def seed_demo(db: Session, reset: bool = False) -> TenantModel:
    random.seed(42)  # Semilla fija para reproducibilidad
    now = datetime.now(timezone.utc)

    # 1. Buscar o crear empresa demo
    demo = db.scalar(select(TenantModel).where(TenantModel.is_sandbox.is_(True)))
    if not demo:
        demo = db.scalar(select(TenantModel).where(TenantModel.slug == "demo"))

    if demo:
        if not demo.is_sandbox:
            raise RuntimeError("Existe una empresa con slug 'demo' que no es sandbox. Abortando por seguridad.")
        if reset:
            # Limpiar datos dependientes de la demo
            demo_id = demo.id
            db.execute(delete(ProductImageModel).where(ProductImageModel.tenant_id == demo_id))
            db.execute(delete(ProductVariantModel).where(ProductVariantModel.tenant_id == demo_id))
            db.execute(delete(ProductModel).where(ProductModel.tenant_id == demo_id))
            db.execute(delete(CashPointModel).where(CashPointModel.tenant_id == demo_id))
            db.execute(delete(BranchModel).where(BranchModel.tenant_id == demo_id))
            db.commit()
    else:
        demo = TenantModel(
            trade_name="FashionStore Demo",
            legal_name="FashionStore Sandbox S.R.L.",
            tax_id="DEMO-999999",
            contact_email="demo@fashionstore.test",
            contact_phone="+591 70000000",
            slug="demo",
            is_sandbox=True,
            status="ACTIVA",
            is_active=True,
            created_at=now - timedelta(days=180),
        )
        db.add(demo)
        db.commit()
        db.refresh(demo)

    demo_id = demo.id

    # 2. Ciudad base
    city = db.scalar(select(CityModel).where(CityModel.name == "Santa Cruz de la Sierra"))
    if not city:
        city = CityModel(name="Santa Cruz de la Sierra", department="Santa Cruz", country="Bolivia")
        db.add(city)
        db.flush()

    # 3. 3 Sucursales y cajas
    existing_branches = db.scalars(select(BranchModel).where(BranchModel.tenant_id == demo_id)).all()
    if not existing_branches:
        branch_configs = [
            ("Central Equipetrol", "SUC-DEMO-01", "Av. San Martín #450"),
            ("Mall Las Brisas", "SUC-DEMO-02", "Av. Cristo Redentor 4to Anillo"),
            ("Centro Histórico", "SUC-DEMO-03", "Calle 24 de Septiembre #120"),
        ]
        created_branches = []
        for name, code, addr in branch_configs:
            br = BranchModel(
                tenant_id=demo_id,
                name=name,
                code=code,
                address=addr,
                city_id=city.id,
                is_active=True,
                created_at=now - timedelta(days=180),
            )
            db.add(br)
            db.flush()
            created_branches.append(br)

            cp = CashPointModel(
                tenant_id=demo_id,
                branch_id=br.id,
                code=f"CAJA-{code[-2:]}-1",
                name=f"Caja Principal {name}",
                is_active=True,
                created_at=now - timedelta(days=180),
            )
            db.add(cp)
        db.commit()

    # 4. Tallas y colores
    tallas_codigos = ["XS", "S", "M", "L", "XL"]
    colores_configs = [("Negro", "#000000"), ("Blanco", "#FFFFFF"), ("Rojo", "#E53E3E"), ("Azul Marino", "#1A365D")]

    tallas = []
    for t in tallas_codigos:
        sz = db.scalar(select(SizeModel).where(SizeModel.tenant_id == demo_id, SizeModel.name == t))
        if not sz:
            sz = SizeModel(tenant_id=demo_id, name=t, size_system="US")
            db.add(sz)
            db.flush()
        tallas.append(sz)

    colores = []
    for c_name, c_hex in colores_configs:
        clr = db.scalar(select(ColorModel).where(ColorModel.tenant_id == demo_id, ColorModel.name == c_name))
        if not clr:
            clr = ColorModel(tenant_id=demo_id, name=c_name, hex_code=c_hex)
            db.add(clr)
            db.flush()
        colores.append(clr)

    # 5. Categoría demo
    cat = db.scalar(select(CategoryModel).where(CategoryModel.tenant_id == demo_id, CategoryModel.name == "Colección Demo"))
    if not cat:
        cat = CategoryModel(tenant_id=demo_id, name="Colección Demo", slug="coleccion-demo")
        db.add(cat)
        db.flush()

    # 6. Prendas y variantes (hasta 120 prendas)
    current_prod_count = db.scalar(select(func.count(ProductModel.id)).where(ProductModel.tenant_id == demo_id)) or 0
    if current_prod_count < 120:
        needed = 120 - current_prod_count
        prendas_nombres = [
            "Vestido Casual", "Blusa de Seda", "Pantalón Denim", "Chaqueta Cuero",
            "Falda Plisada", "Camisa Oxford", "Top Lencero", "Saco Sastrería",
            "Enterizo Elegante", "Cardigan Tejido", "Short Lino", "Polera Básica",
        ]

        for i in range(needed):
            idx = current_prod_count + i + 1
            tipo = prendas_nombres[i % len(prendas_nombres)]
            p_name = f"{tipo} Modelo {idx:03d}"
            p_price = Decimal(random.randint(90, 450))

            prod = ProductModel(
                tenant_id=demo_id,
                name=p_name,
                description=f"Prenda de demostración {idx} con tejido de alta calidad.",
                base_price=p_price,
                is_active=True,
                category_id=cat.id,
                created_at=now - timedelta(days=random.randint(10, 170)),
            )
            db.add(prod)
            db.flush()

            # 4 variantes por prenda
            for v_idx in range(4):
                sz = tallas[v_idx % len(tallas)]
                clr = colores[v_idx % len(colores)]
                sku = f"DEMO-{idx:03d}-{sz.name}-{clr.name[:2].upper()}"

                var = ProductVariantModel(
                    tenant_id=demo_id,
                    product_id=prod.id,
                    sku=sku,
                    size_id=sz.id,
                    color_id=clr.id,
                    price_adjustment=Decimal("0.00"),
                    is_active=True,
                )
                db.add(var)

        db.commit()

    return demo


def main():
    parser = argparse.ArgumentParser(description="Sembrador de empresa demo para sandbox")
    parser.add_argument("--reset", action="store_true", help="Reinicia la base de datos de la empresa demo")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        demo = seed_demo(db, reset=args.reset)
        print(f"Empresa demo lista: '{demo.trade_name}' (ID: {demo.id}, Slug: {demo.slug})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
