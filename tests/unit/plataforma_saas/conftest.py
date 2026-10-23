from datetime import date, timedelta
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
from src.plataforma_saas.domain.estados import FUNCIONES
from src.inventario_sucursales.infrastructure.models.organization import CityModel, BranchModel
from src.usuarios_catalogo.infrastructure.models.catalog import CategoryModel, SizeModel, ColorModel, ProductModel, ProductVariantModel
from src.ventas_pagos.infrastructure.models import StockModel

TEST_PASSWORD = "Saas_Test2026!Strong"


def create_world(engine=None):
    """Mundo 100% local, reutilizable para QA visual y contratos HTTP."""
    engine = engine or create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    codes = ["tenants.read", "tenants.write", "plans.read", "plans.write", "subscriptions.read", "subscriptions.write", "my_subscription.read", "branches.read", "branches.write", "catalog.read", "catalog.write", "reservations.read", "reservations.write", "users.read", "users.write"]
    permissions = [PermissionModel(code=code, name=code, module=code.split(".")[0]) for code in codes]
    platform_role = RoleModel(code="platform_admin", name="Plataforma", is_system=True, permissions=permissions[:6])
    admin_role = RoleModel(code="admin", name="Administrador", permissions=permissions[6:])
    client_role = RoleModel(code="client", name="Cliente")
    platform = UserModel(email="plataforma@example.com", first_name="Admin", last_name="Plataforma", password_hash=PasswordHasher().hash(TEST_PASSWORD), is_verified=True, roles=[platform_role])
    plans = []
    for code, limit in [("BASICO", 2), ("PROFESIONAL", 10)]:
        plan = PlanModel(code=code, name=code.title(), reference_price=350 if code == "BASICO" else 890, duration_days=30,
            features=[PlanFeatureModel(feature_code=feature, enabled=code == "PROFESIONAL" or feature not in ("ai_reports", "ml_analytics")) for feature in FUNCIONES]+[PlanFeatureModel(feature_code="max_active_branches", enabled=True, limit_value=limit)])
        plans.append(plan)
    db.add_all([platform, admin_role, client_role, *plans])
    db.flush()
    tenants = [TenantModel(legal_name="Empresa "+suffix, trade_name="Moda "+suffix, tax_id="10000"+suffix, slug="moda-"+suffix.lower(), contact_email=f"contacto{suffix}@example.com") for suffix in ("A", "B")]
    city = CityModel(name="Santa Cruz", department="Santa Cruz")
    category, size, color = CategoryModel(name="Vestidos", slug="vestidos"), SizeModel(code="M", name="Mediana"), ColorModel(name="Rojo", hex_code="#ff0000")
    db.add_all([*tenants, city, category, size, color])
    db.flush()
    admins, customers, branches, products, variants = [], [], [], [], []
    for number, tenant in enumerate(tenants):
        db.add(SubscriptionModel(tenant_id=tenant.id, plan_id=plans[number].id, start_date=date.today(), end_date=date.today()+timedelta(days=29), status="ACTIVA"))
        admin = UserModel(tenant_id=tenant.id, email=f"admin{number}@example.com", first_name="Admin", last_name=str(number), password_hash=platform.password_hash, is_verified=True, roles=[admin_role])
        customer = UserModel(tenant_id=tenant.id, email=f"cliente{number}@example.com", first_name="Cliente", last_name=str(number), document_number=f"98765432{number}", phone="70000000", password_hash=platform.password_hash, is_verified=True, roles=[client_role])
        branch = BranchModel(tenant_id=tenant.id, code="CENTRAL", name="Central", city_id=city.id, address="Av. Principal")
        product = ProductModel(tenant_id=tenant.id, name=f"Prenda {number}", slug="prenda-demo", description="Prenda local", base_price=150, category_id=category.id,
            variants=[ProductVariantModel(size_id=size.id, color_id=color.id, sku=f"SKU-{number}")])
        db.add_all([admin, customer, branch, product])
        db.flush()
        db.add(StockModel(variant_id=product.variants[0].id, branch_id=branch.id, quantity=20))
        admins.append(admin); customers.append(customer); branches.append(branch); products.append(product); variants.append(product.variants[0])
    db.commit()
    app = create_app()
    def session_override():
        try:
            yield db
        except Exception:
            db.rollback()
            raise
    app.dependency_overrides[get_db] = session_override
    def headers(user):
        token, _ = JWTService().create_access_token(str(user.id), str(user.tenant_id) if user.tenant_id else None)
        return {"Authorization": f"Bearer {token}"}
    return SimpleNamespace(db=db, engine=engine, app=app, client=TestClient(app), headers=headers, platform=platform,
        tenants=tenants, plans=plans, admins=admins, customers=customers, branches=branches, products=products, variants=variants,
        category=category, size=size, color=color, admin_role=admin_role, client_role=client_role)


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(AuthEmailService, "send_tenant_invitation", lambda *args: False)
    world = create_world()
    yield world
    world.client.close()
    world.db.close()
    world.engine.dispose()
