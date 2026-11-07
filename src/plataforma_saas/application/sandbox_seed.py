from datetime import date, datetime, timedelta, timezone
from random import Random

from sqlalchemy import or_, select, text

from src.inventario_sucursales.infrastructure.models.organization import BranchModel, CashPointModel, CityModel
from src.plataforma_saas.domain.exceptions import SandboxOnlyError
from src.plataforma_saas.infrastructure.models.plan import PlanModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.infrastructure.repositories.saas_repository import SaasRepository
from src.shared.exceptions.domain_exception import ConflictError
from src.usuarios_catalogo.infrastructure.models.catalog import (
    CategoryModel, ColorModel, ProductModel, ProductVariantModel, SizeModel,
)
from src.ventas_pagos.infrastructure.models import StockModel


def _obtener_o_crear(db, model, **keys):
    row = db.scalar(select(model).filter_by(**keys))
    if row is None:
        row = model(**keys)
        db.add(row)
    return row


def seed_demo(db, reset: bool = False) -> TenantModel:
    """Prepara datos reproducibles sin borrar las referencias del historial."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(98462052)"))
    demo = db.scalar(select(TenantModel).where(TenantModel.is_sandbox.is_(True)).with_for_update())
    if demo is None:
        collision = db.scalar(select(TenantModel.id).where(or_(
            TenantModel.slug == "demo", TenantModel.tax_id == "DEMO-999999",
        )).limit(1))
        if collision is not None:
            raise SandboxOnlyError("El identificador de la demo está ocupado por una empresa real.")
        demo = TenantModel(
            trade_name="FashionStore Demo", legal_name="FashionStore Sandbox S.R.L.",
            tax_id="DEMO-999999", contact_email="demo@fashionstore.test", slug="demo", is_sandbox=True,
        )
        db.add(demo)
    demo.status = "ACTIVA"
    demo.is_published = False
    db.flush()

    hoy = date.today()
    subscription = SaasRepository(db).open_subscription(demo.id)
    if subscription is None or subscription.status != "ACTIVA" or subscription.end_date < hoy:
        plan = db.scalar(select(PlanModel).where(PlanModel.code == "PROFESIONAL", PlanModel.is_active.is_(True)))
        if plan is None:
            raise ConflictError("Se requiere un plan Profesional activo para preparar la demo.")
        if subscription is not None:
            if subscription.stripe_subscription_id:
                raise ConflictError("La suscripción externa de la demo debe revisarse antes de renovarla.")
            subscription.closed_at = datetime.now(timezone.utc)
            db.flush()
        db.add(SubscriptionModel(
            tenant_id=demo.id, plan_id=plan.id, start_date=hoy, end_date=hoy + timedelta(days=365),
            status="ACTIVA", reason="Suscripción interna de demostración",
        ))

    city = _obtener_o_crear(db, CityModel, name="Santa Cruz de la Sierra", department="Santa Cruz", country="Bolivia")
    db.flush()
    branch_names = ("Central Equipetrol", "Mall Las Brisas", "Centro Histórico")
    branch_codes = [f"SUC-DEMO-{index:02}" for index in range(1, 4)]
    branches = []
    for code, name in zip(branch_codes, branch_names):
        branch = _obtener_o_crear(db, BranchModel, tenant_id=demo.id, code=code)
        branch.name, branch.city_id, branch.address = name, city.id, f"Sucursal de demostración {name}"
        branch.is_active, branch.deleted_at = True, None
        db.flush()
        cash = _obtener_o_crear(db, CashPointModel, tenant_id=demo.id, branch_id=branch.id, code="CAJA-DEMO")
        cash.name, cash.is_active, cash.deleted_at = "Caja de demostración", True, None
        branches.append(branch)

    sizes = []
    for code in ("XS", "S", "M", "L"):
        size = _obtener_o_crear(db, SizeModel, tenant_id=demo.id, code=code)
        size.name, size.is_active = size.code, True
        sizes.append(size)
    colors = []
    for name, hex_code in (("Negro", "#000000"), ("Blanco", "#FFFFFF"), ("Rojo", "#E53E3E"), ("Azul Marino", "#1A365D")):
        color = db.scalar(select(ColorModel).where(
            ColorModel.tenant_id == demo.id,
            or_(ColorModel.name == name, ColorModel.hex_code == hex_code),
        ).order_by((ColorModel.name == name).desc()).limit(1))
        if color is None:
            color = ColorModel(tenant_id=demo.id, name=name, hex_code=hex_code)
            db.add(color)
        color.is_active = True
        colors.append(color)
    category = _obtener_o_crear(db, CategoryModel, tenant_id=demo.id, slug="coleccion-demo")
    category.name, category.is_active = "Colección Demo", True
    db.flush()

    slugs = {f"prenda-demo-{number:03}": number for number in range(1, 121)}
    products = {row.slug: row for row in db.scalars(select(ProductModel).where(ProductModel.tenant_id == demo.id))}
    demo_products = []
    rng = Random(42)
    styles = ("Vestido Casual", "Blusa de Seda", "Pantalón Denim", "Chaqueta", "Falda Plisada", "Camisa Oxford")
    for slug, number in slugs.items():
        price = rng.randint(90, 450)
        product = products.get(slug)
        if product is None:
            product = ProductModel(tenant_id=demo.id, slug=slug)
            db.add(product)
        if product.id is None or reset:
            product.name = f"{styles[(number - 1) % len(styles)]} {number:03}"
            product.description = f"Prenda sintética de demostración {number}."
            product.category_id, product.base_price = category.id, price
            product.is_active, product.deleted_at = True, None
        demo_products.append((number, product))
    db.flush()

    demo_variants = []
    for number, product in demo_products:
        variants = {(row.size_id, row.color_id): row for row in product.variants} if product.slug in products else {}
        existing_skus = {row.sku for row in variants.values()}
        for size, color in zip(sizes, colors):
            variant = variants.get((size.id, color.id))
            if variant is None:
                sku = f"FS-DEMO-{demo.id.hex}-{number:03}-{size.code}"
                if sku in existing_skus:
                    sku = f"{sku}-{color.id.hex[:8]}"
                variant = ProductVariantModel(product_id=product.id, size_id=size.id, color_id=color.id, sku=sku)
                db.add(variant)
            variant.is_active = True
            demo_variants.append(variant)
    db.flush()

    stock_by_key = {
        (row.variant_id, row.branch_id): row
        for row in db.scalars(select(StockModel).where(
            StockModel.variant_id.in_([variant.id for variant in demo_variants]),
            StockModel.branch_id.in_([branch.id for branch in branches]),
        ))
    }
    for variant in demo_variants:
        for branch in branches:
            stock = stock_by_key.get((variant.id, branch.id))
            if stock is None:
                db.add(StockModel(variant_id=variant.id, branch_id=branch.id, quantity=20))
            elif reset:
                stock.quantity = 20

    if reset:
        for slug, product in products.items():
            if slug not in slugs:
                product.is_active = False
        for branch in db.scalars(select(BranchModel).where(BranchModel.tenant_id == demo.id, BranchModel.code.not_in(branch_codes))):
            branch.is_active = False
    db.flush()
    return demo
