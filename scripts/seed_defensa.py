"""Sembrador maestro de datos de demostración para la defensa final del 2do Parcial.

Siembra dos empresas independientes con datos realistas para demostrar:
1. Urbano Boutique (Plan Profesional):
   - 4 sucursales en Santa Cruz (Centro, Equipetrol, Ventura, Las Brisas)
   - 6 usuarios con distintos roles (Administrador, Encargado, Cajeros, Vendedor)
   - Catálogo de moda con categorías, temporadas, prendas y variantes con fotos
   - Ofertas y promociones activas (CU-11)
   - Dispositivos PWA y Android registrados y activos (CU-12)
   - Identidad de marca azul (#1e40af)
2. Moda Cruceña (Plan Básico):
   - 2 sucursales (Centro, Villa 1ro de Mayo)
   - 5 usuarios
   - Catálogo regional con existencias
   - Dispositivo bloqueado para demostrar rechazo 403 y registro en auditoría (CU-12)
   - Identidad de marca vino (#74394e)

Uso:
  python -m scripts.seed_defensa [--dry-run]
"""
import argparse
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import random
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.security.password_hasher import PasswordHasher
from src.dispositivos.infrastructure.models import DeviceModel
from src.infrastructure.database.session import SessionLocal
from src.inventario_sucursales.infrastructure.models.organization import (
    BranchModel,
    CashPointModel,
    CityModel,
)
from src.plataforma_saas.infrastructure.models.plan import PlanModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.roles.infrastructure.persistence.models.role import RoleModel
from src.usuarios_catalogo.infrastructure.models.catalog import (
    CategoryModel,
    ColorModel,
    ProductModel,
    ProductVariantModel,
    SeasonModel,
    SizeModel,
)
from src.ventas_pagos.infrastructure.engagement_models import PromotionModel, PromotionTargetModel
from src.ventas_pagos.infrastructure.models import StockModel

DEFAULT_PW = "Moda2026!Defensa"


def ensure_city(db: Session) -> CityModel:
    city = db.scalar(select(CityModel).where(CityModel.name == "Santa Cruz"))
    if not city:
        city = CityModel(
            name="Santa Cruz",
            department="Santa Cruz",
            country="Bolivia",
            is_active=True,
        )
        db.add(city)
        db.flush()
    return city


def ensure_roles(db: Session) -> dict[str, RoleModel]:
    roles = {}
    for code in ("admin", "store_manager", "cashier", "client"):
        r = db.scalar(select(RoleModel).where(RoleModel.code == code))
        if r:
            roles[code] = r
    return roles


def seed_urbano_boutique(db: Session, city: CityModel, roles: dict[str, RoleModel], hasher: PasswordHasher) -> TenantModel:
    now = datetime.now(timezone.utc)
    tenant = db.scalar(select(TenantModel).where(TenantModel.slug == "urbano"))
    if not tenant:
        tenant = TenantModel(
            id=uuid.uuid4(),
            legal_name="Urbano Boutique S.R.L.",
            trade_name="Urbano Boutique",
            tax_id="7788990011",
            slug="urbano",
            contact_email="contacto@urbanoboutique.bo",
            phone="+591 71020304",
            status="ACTIVA",
            is_sandbox=False,
        )
        db.add(tenant)
        db.flush()

    # Plan Profesional
    prof_plan = db.scalar(select(PlanModel).where(PlanModel.code == "PROFESIONAL"))
    sub = db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id == tenant.id))
    if not sub and prof_plan:
        sub = SubscriptionModel(
            tenant_id=tenant.id,
            plan_id=prof_plan.id,
            start_date=date.today() - timedelta(days=60),
            end_date=date.today() + timedelta(days=305),
            status="ACTIVA",
        )
        db.add(sub)
        db.flush()

    # Sucursales
    sucursales_def = [
        ("URB-CENTRO", "Sucursal Centro - Calle 21 de Mayo", "Calle 21 de Mayo #234"),
        ("URB-EQUIPETROL", "Sucursal Equipetrol - Av. San Martín", "Av. San Martín esq. Calle 5"),
        ("URB-VENTURA", "Sucursal Ventura Mall", "Ventura Mall Local 104"),
        ("URB-BRISAS", "Sucursal Las Brisas", "Centro Comercial Las Brisas Nivel 2"),
    ]
    branches = []
    for code, name, addr in sucursales_def:
        b = db.scalar(select(BranchModel).where(BranchModel.tenant_id == tenant.id, BranchModel.code == code))
        if not b:
            b = BranchModel(
                tenant_id=tenant.id,
                code=code,
                name=name,
                city_id=city.id,
                address=addr,
                is_active=True,
            )
            db.add(b)
            db.flush()
            # Caja
            cp = CashPointModel(tenant_id=tenant.id, branch_id=b.id, code=f"CAJA-{code[-3:]}", name=f"Caja Principal {name.split('-')[0].strip()}")
            db.add(cp)
        branches.append(b)

    # Usuarios
    users_def = [
        ("admin@urbanoboutique.bo", "Valeria", "Méndez", "admin"),
        ("gerente@urbanoboutique.bo", "Carlos", "Suárez", "store_manager"),
        ("caja.centro@urbanoboutique.bo", "Mariana", "Roca", "cashier"),
        ("caja.equipetrol@urbanoboutique.bo", "Jorge", "Peña", "cashier"),
        ("caja.ventura@urbanoboutique.bo", "Lucía", "Vaca", "cashier"),
        ("cliente.demo@urbanoboutique.bo", "Andrea", "Camacho", "client"),
    ]
    for email, fn, ln, r_code in users_def:
        u = db.scalar(select(UserModel).where(UserModel.tenant_id == tenant.id, UserModel.email == email))
        if not u and r_code in roles:
            u = UserModel(
                tenant_id=tenant.id,
                email=email,
                first_name=fn,
                last_name=ln,
                password_hash=hasher.hash(DEFAULT_PW),
                is_verified=True,
                roles=[roles[r_code]],
            )
            db.add(u)
    db.flush()

    # Categorías y prendas
    cat_vestidos = db.scalar(select(CategoryModel).where(CategoryModel.tenant_id == tenant.id, CategoryModel.slug == "vestidos"))
    if not cat_vestidos:
        cat_vestidos = CategoryModel(tenant_id=tenant.id, name="Vestidos de Fiesta", slug="vestidos")
        db.add(cat_vestidos)
        db.flush()

    sz_m = db.scalar(select(SizeModel).where(SizeModel.tenant_id == tenant.id, SizeModel.code == "M"))
    if not sz_m:
        sz_m = SizeModel(tenant_id=tenant.id, code="M", name="Mediana")
        db.add(sz_m)
        db.flush()

    col_azul = db.scalar(select(ColorModel).where(ColorModel.tenant_id == tenant.id, ColorModel.name == "Azul Real"))
    if not col_azul:
        col_azul = ColorModel(tenant_id=tenant.id, name="Azul Real", hex_code="#1e40af")
        db.add(col_azul)
        db.flush()

    prod = db.scalar(select(ProductModel).where(ProductModel.tenant_id == tenant.id, ProductModel.slug == "vestido-gala-seda"))
    if not prod:
        prod = ProductModel(
            tenant_id=tenant.id,
            name="Vestido de Gala en Seda Azul",
            slug="vestido-gala-seda",
            description="Vestido de noche confeccionado en seda italiana de alta densidad con caída fluida.",
            base_price=Decimal("450.00"),
            category_id=cat_vestidos.id,
            is_featured=True,
        )
        db.add(prod)
        db.flush()
        var = ProductVariantModel(
            product_id=prod.id,
            size_id=sz_m.id,
            color_id=col_azul.id,
            sku="URB-VES-AZ-M",
            is_active=True,
        )
        db.add(var)
        db.flush()
        for b in branches:
            db.add(StockModel(variant_id=var.id, branch_id=b.id, quantity=15))

    # Oferta activa (CU-11)
    promo = db.scalar(select(PromotionModel).where(PromotionModel.tenant_id == tenant.id, PromotionModel.code == "VERANO25"))
    if not promo:
        promo = PromotionModel(
            tenant_id=tenant.id,
            name="Temporada de Verano 25%",
            code="VERANO25",
            description="25% de descuento en vestidos y prendas seleccionadas",
            discount_type="percent",
            discount_value=Decimal("25.00"),
            minimum_order=Decimal("100.00"),
            applies_online=True,
            applies_pos=True,
            applies_offline=True,
            is_active=True,
            starts_at=now - timedelta(days=10),
            ends_at=now + timedelta(days=20),
            max_uses=500,
            uses_count=12,
        )
        db.add(promo)
        db.flush()
        db.add(PromotionTargetModel(promotion_id=promo.id, target_type="CATEGORY", target_id=cat_vestidos.id))

    # Dispositivo PWA Activo (CU-12)
    dev_pwa = db.scalar(select(DeviceModel).where(DeviceModel.tenant_id == tenant.id, DeviceModel.device_id == "pwa-caja-centro-urbano"))
    if not dev_pwa:
        dev_pwa = DeviceModel(
            tenant_id=tenant.id,
            device_id="pwa-caja-centro-urbano",
            platform="PWA",
            label="Terminal Mostrador Centro 01",
            branch_id=branches[0].id,
            app_version="web-2026.11.08",
            first_seen_at=now - timedelta(days=15),
            last_snapshot_at=now - timedelta(hours=2),
            last_sync_at=now - timedelta(minutes=15),
            status="ACTIVO",
        )
        db.add(dev_pwa)

    db.flush()
    return tenant


def seed_moda_crucena(db: Session, city: CityModel, roles: dict[str, RoleModel], hasher: PasswordHasher) -> TenantModel:
    now = datetime.now(timezone.utc)
    tenant = db.scalar(select(TenantModel).where(TenantModel.slug == "moda-crucena"))
    if not tenant:
        tenant = TenantModel(
            id=uuid.uuid4(),
            legal_name="Moda Cruceña Confecciones",
            trade_name="Moda Cruceña",
            tax_id="4455667788",
            slug="moda-crucena",
            contact_email="gerencia@modacrucena.com.bo",
            phone="+591 72030405",
            status="ACTIVA",
            is_sandbox=False,
        )
        db.add(tenant)
        db.flush()

    # Plan Básico (2 sucursales)
    basico_plan = db.scalar(select(PlanModel).where(PlanModel.code == "BASICO"))
    sub = db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id == tenant.id))
    if not sub and basico_plan:
        sub = SubscriptionModel(
            tenant_id=tenant.id,
            plan_id=basico_plan.id,
            start_date=date.today() - timedelta(days=45),
            end_date=date.today() + timedelta(days=15),
            status="ACTIVA",
        )
        db.add(sub)
        db.flush()

    # Sucursales (exactamente 2)
    sucursales_def = [
        ("MCR-CENTRO", "Sucursal Central - Calle Junín", "Calle Junín #150"),
        ("MCR-VILLA", "Sucursal Villa 1ro de Mayo", "Av. Principal Villa 1ro de Mayo"),
    ]
    branches = []
    for code, name, addr in sucursales_def:
        b = db.scalar(select(BranchModel).where(BranchModel.tenant_id == tenant.id, BranchModel.code == code))
        if not b:
            b = BranchModel(
                tenant_id=tenant.id,
                code=code,
                name=name,
                city_id=city.id,
                address=addr,
                is_active=True,
            )
            db.add(b)
            db.flush()
            cp = CashPointModel(tenant_id=tenant.id, branch_id=b.id, code=f"CAJA-{code[-3:]}", name=f"Caja {name.split('-')[0].strip()}")
            db.add(cp)
        branches.append(b)

    # Usuarios
    users_def = [
        ("admin@modacrucena.com.bo", "Gabriela", "Paz", "admin"),
        ("encargado@modacrucena.com.bo", "Fernando", "Rojas", "store_manager"),
        ("cajero1@modacrucena.com.bo", "Susana", "Arteaga", "cashier"),
        ("cajero2@modacrucena.com.bo", "Miguel", "Terrazas", "cashier"),
        ("cliente@modacrucena.com.bo", "Patricia", "Flores", "client"),
    ]
    for email, fn, ln, r_code in users_def:
        u = db.scalar(select(UserModel).where(UserModel.tenant_id == tenant.id, UserModel.email == email))
        if not u and r_code in roles:
            u = UserModel(
                tenant_id=tenant.id,
                email=email,
                first_name=fn,
                last_name=ln,
                password_hash=hasher.hash(DEFAULT_PW),
                is_verified=True,
                roles=[roles[r_code]],
            )
            db.add(u)
    db.flush()

    # Dispositivo Bloqueado para demostración de seguridad (CU-12)
    dev_bloqueado = db.scalar(select(DeviceModel).where(DeviceModel.tenant_id == tenant.id, DeviceModel.device_id == "android-pos-extraviado-007"))
    if not dev_bloqueado:
        admin_user = db.scalar(select(UserModel).where(UserModel.tenant_id == tenant.id, UserModel.email == "admin@modacrucena.com.bo"))
        dev_bloqueado = DeviceModel(
            tenant_id=tenant.id,
            device_id="android-pos-extraviado-007",
            platform="ANDROID",
            label="Teléfono POS Móvil Sucursal Villa",
            branch_id=branches[1].id,
            user_id=admin_user.id if admin_user else None,
            app_version="app-1.4.0 (27)",
            first_seen_at=now - timedelta(days=20),
            last_snapshot_at=now - timedelta(days=2),
            last_sync_at=now - timedelta(days=2),
            status="BLOQUEADO",
            blocked_by=admin_user.id if admin_user else None,
            blocked_at=now - timedelta(days=1),
            block_reason="Terminal reportado como extraviado en transporte público",
            rejected_attempts=3,
            last_rejected_at=now - timedelta(hours=3),
        )
        db.add(dev_bloqueado)

    db.flush()
    return tenant


def main():
    parser = argparse.ArgumentParser(description="Sembrador de datos para la defensa.")
    parser.add_argument("--dry-run", action="store_true", help="Verifica sin comitear cambios.")
    args = parser.parse_args()

    db = SessionLocal()
    hasher = PasswordHasher()
    try:
        print("🌱 Iniciando siembra de datos de demostración para la defensa...")
        city = ensure_city(db)
        roles = ensure_roles(db)

        t_urbano = seed_urbano_boutique(db, city, roles, hasher)
        print(f"✅ Urbano Boutique sembrada ({t_urbano.slug}) - Plan Profesional, 4 sucursales, ofertas y dispositivos activos.")

        t_moda = seed_moda_crucena(db, city, roles, hasher)
        print(f"✅ Moda Cruceña sembrada ({t_moda.slug}) - Plan Básico, 2 sucursales, 1 dispositivo bloqueado (CU-12).")

        if args.dry_run:
            db.rollback()
            print("🔍 Dry-run completado: cambios revertidos.")
        else:
            db.commit()
            print("🚀 Siembra completada con éxito.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
