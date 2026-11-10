from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from src.main import create_app
from src.infrastructure.database.base import Base
from src.infrastructure.database.session import get_db
from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.security.password_hasher import PasswordHasher
from src.auth.infrastructure.security.jwt_service import JWTService
from src.auth.application.services.auth_email_service import AuthEmailService
from src.roles.infrastructure.persistence.models.role import RoleModel
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.infrastructure.models.plan import PlanModel, PlanFeatureModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.models.support_session import SupportSessionModel
from src.plataforma_saas.infrastructure.models.module import PlatformModuleModel, ModulePermissionModel
from src.plataforma_saas.domain.estados import FUNCIONES
from src.inventario_sucursales.infrastructure.models.organization import CityModel, BranchModel, CashPointModel
from src.usuarios_catalogo.infrastructure.models.catalog import CategoryModel, SizeModel, ColorModel, ProductModel, ProductVariantModel
from src.ventas_pagos.infrastructure.models import StockModel

TEST_PASSWORD = "Saas_Test2026!Strong"


def create_world(engine=None):
    """Mundo 100% local, reutilizable para QA visual y contratos HTTP."""
    engine = engine or create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    codes = [
        "tenants.read", "tenants.write", "plans.read", "plans.write", "subscriptions.read", "subscriptions.write",
        "my_subscription.read", "branches.read", "branches.write", "catalog.read", "catalog.write",
        "reservations.read", "reservations.write", "users.read", "users.write", "cities.write",
        "commerce.read", "commerce.write", "stock.read", "stock.write", "roles.read", "roles.write",
        "support.access", "platform_audit.read", "audit.read", "platform_users.read", "platform_users.write",
        "tenant_profile.write", "support_sessions.read", "dashboard.read", "sync.write", "sync_conflicts.read", "sync_conflicts.resolve", "sync_log.read", "ml_dashboard.read", "ml_models.manage", "exchanges.read", "exchanges.write", "ai_reports.use", "ai_reports.history",
        "promotions.read", "promotions.write", "devices.read", "devices.write",
        "modules.read", "modules.write", "platform_roles.read", "platform_roles.write", "tenant_users.write", "sandbox.manage",
        "storefront.write", "payment_methods.write", "catalog_templates.write", "upgrade_requests.manage",
        "integrations.read", "integrations.write",
    ]
    platform_codes = {
        "tenants.read", "tenants.write", "plans.read", "plans.write", "subscriptions.read", "subscriptions.write",
        "cities.write", "support.access", "platform_audit.read", "platform_users.read", "platform_users.write", "ml_models.manage",
        "modules.read", "modules.write", "platform_roles.read", "platform_roles.write", "tenant_users.write", "sandbox.manage",
        "catalog_templates.write", "upgrade_requests.manage",
    }
    permissions = [
        PermissionModel(
            code=code,
            name=code,
            module=code.split(".")[0],
            scope="platform" if code in platform_codes else "tenant",
        )
        for code in codes
    ]
    platform_role = RoleModel(code="platform_admin", name="Plataforma", is_system=True, audience="PLATFORM", permissions=[p for p in permissions if p.code in platform_codes])
    admin_role = RoleModel(code="admin", name="Administrador", is_system=True, audience="TENANT", permissions=[p for p in permissions if p.code not in platform_codes or p.code == "ml_models.manage"])
    store_manager_role = RoleModel(code="store_manager", name="Encargado de tienda", is_system=True, audience="TENANT")
    cashier_role = RoleModel(code="cashier", name="Cajero", is_system=True, audience="TENANT")
    client_role = RoleModel(code="client", name="Cliente", is_system=True, audience="TENANT")
    platform = UserModel(email="plataforma@example.com", first_name="Admin", last_name="Plataforma", password_hash=PasswordHasher().hash(TEST_PASSWORD), is_verified=True, roles=[platform_role])
    plans = []
    initial_features = tuple(dict.fromkeys((*FUNCIONES, "inventory", "promotions", "virtual_tryon", "devices_audit", "exchanges", "integrations")))
    for code, limit in [("BASICO", 2), ("PROFESIONAL", 10)]:
        plan = PlanModel(code=code, name=code.title(), reference_price=350 if code == "BASICO" else 890, duration_days=30,
            features=[PlanFeatureModel(feature_code=feature, enabled=code == "PROFESIONAL" or feature not in ("ai_reports", "ml_analytics", "integrations")) for feature in initial_features]+[PlanFeatureModel(feature_code="max_active_branches", enabled=True, limit_value=limit)])
        plans.append(plan)
    db.add_all([platform, admin_role, store_manager_role, cashier_role, client_role, *plans])
    db.flush()
    tenants = [TenantModel(id=uuid4(), legal_name="Empresa "+suffix, trade_name="Moda "+suffix, tax_id="10000"+suffix, slug="moda-"+suffix.lower(), contact_email=f"contacto{suffix}@example.com", is_published=True) for suffix in ("A", "B")]
    city = CityModel(name="Santa Cruz", department="Santa Cruz")
    category, size, color = CategoryModel(tenant_id=tenants[0].id, name="Vestidos", slug="vestidos"), SizeModel(tenant_id=tenants[0].id, code="M", name="Mediana"), ColorModel(tenant_id=tenants[0].id, name="Rojo", hex_code="#ff0000")
    category_b, size_b, color_b = CategoryModel(tenant_id=tenants[1].id, name="Vestidos B", slug="vestidos-b"), SizeModel(tenant_id=tenants[1].id, code="M", name="Mediana"), ColorModel(tenant_id=tenants[1].id, name="Rojo", hex_code="#ff0000")
    db.add_all([*tenants, city, category, size, color, category_b, size_b, color_b])
    db.flush()
    admins, customers, branches, products, variants, cash_points = [], [], [], [], [], []
    for number, tenant in enumerate(tenants):
        db.add(SubscriptionModel(tenant_id=tenant.id, plan_id=plans[number].id, start_date=date.today(), end_date=date.today()+timedelta(days=29), status="ACTIVA"))
        admin = UserModel(tenant_id=tenant.id, email=f"admin{number}@example.com", first_name="Admin", last_name=str(number), password_hash=platform.password_hash, is_verified=True, roles=[admin_role])
        customer = UserModel(tenant_id=tenant.id, email=f"cliente{number}@example.com", first_name="Cliente", last_name=str(number), document_number=f"98765432{number}", phone="70000000", password_hash=platform.password_hash, is_verified=True, roles=[client_role])
        branch = BranchModel(tenant_id=tenant.id, name="Central" if number == 0 else f"Sucursal {number}", code="CENTRAL" if number == 0 else f"SUC-0{number}", address=f"Av. Moda {number}", city_id=city.id, is_active=True)
        db.add_all([admin, customer, branch])
        db.flush()
        cash_point = CashPointModel(tenant_id=tenant.id, branch_id=branch.id, code=f"CAJA-0{number}", name=f"Caja {number}", is_active=True)
        product = ProductModel(tenant_id=tenant.id, name="Vestido Demo", slug="prenda-demo", description="Lino", base_price=150.0, category_id=category.id if number == 0 else category_b.id, is_active=True)
        db.add_all([cash_point, product])
        db.flush()
        variant = ProductVariantModel(product_id=product.id, sku=f"SKU-{number}", size_id=size.id if number == 0 else size_b.id, color_id=color.id if number == 0 else color_b.id, is_active=True)
        db.add(variant)
        db.flush()
        db.add(StockModel(branch_id=branch.id, variant_id=variant.id, quantity=20))
        admins.append(admin); customers.append(customer); branches.append(branch); products.append(product); variants.append(variant); cash_points.append(cash_point)
    db.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    test_client = TestClient(app)

    def get_headers(u: UserModel):
        tok, _ = JWTService().create_access_token(str(u.id), tenant_id=str(u.tenant_id) if u.tenant_id else None)
        return {"Authorization": f"Bearer {tok}"}

    return SimpleNamespace(
        engine=engine,
        db=db,
        app=app,
        client=test_client,
        headers=get_headers,
        platform=platform,
        platform_user=platform,
        platform_role=platform_role,
        admin_role=admin_role,
        store_manager_role=store_manager_role,
        cashier_role=cashier_role,
        client_role=client_role,
        roles=[platform_role, admin_role, store_manager_role, cashier_role, client_role],
        category=category,
        size=size,
        color=color,
        tenants=tenants,
        tenant_a=tenants[0],
        tenant_b=tenants[1],
        plans=plans,
        plan_basico=plans[0],
        plan_pro=plans[1],
        admins=admins,
        admin_a=admins[0],
        admin_b=admins[1],
        customers=customers,
        customer_a=customers[0],
        customer_b=customers[1],
        branches=branches,
        branch_a=branches[0],
        branch_b=branches[1],
        products=products,
        product_a=products[0],
        product_b=products[1],
        variants=variants,
        variant_a=variants[0],
        variant_b=variants[1],
        cash_points=cash_points,
        cash_point_a=cash_points[0],
        cash_point_b=cash_points[1],
    )


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(AuthEmailService, "send_tenant_invitation", lambda *args: False)
    monkeypatch.setattr(AuthEmailService, "send_verification", lambda *args: False)
    w = create_world()
    yield w
    w.client.close()
    w.db.close()
    w.engine.dispose()


@pytest.fixture
def client(world):
    return world.client


def make_token(user: UserModel, session_id=None, read_only=False):
    if session_id:
        token, _ = JWTService().create_support_token(
            user_id=str(user.id),
            tenant_id=str(user.tenant_id),
            session_id=str(session_id),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            read_only=read_only,
        )
        return token
    token, _ = JWTService().create_access_token(
        user_id=str(user.id),
        tenant_id=str(user.tenant_id) if user.tenant_id else None,
    )
    return token
