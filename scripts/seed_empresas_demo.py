"""Empresa y datos mínimos para demostrar aislamiento en una base local."""
import os
from datetime import date, timedelta
from sqlalchemy import select
from src.auth.domain.password_policy import PasswordPolicy
from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.security.password_hasher import PasswordHasher
from src.roles.infrastructure.persistence.models.role import RoleModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.infrastructure.models.plan import PlanModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.inventario_sucursales.infrastructure.models.organization import CityModel, BranchModel
from src.usuarios_catalogo.infrastructure.models.catalog import CategoryModel, ProductModel

def sembrar(db, password):
    email = 'admin.urbano@example.com'
    PasswordPolicy.validate(password, email=email)
    plan = db.scalar(select(PlanModel).where(PlanModel.code == 'PROFESIONAL'))
    role = db.scalar(select(RoleModel).where(RoleModel.code == 'admin'))
    if not plan or not role:
        raise ValueError('Faltan planes y roles; aplica las migraciones en la base local.')
    tenant = db.scalar(select(TenantModel).where(TenantModel.slug == 'urbano'))
    if tenant is None:
        tenant = TenantModel(legal_name='Urbano Demo S.R.L.', trade_name='Urbano Boutique', tax_id='9000000002', slug='urbano', contact_email='contacto.urbano@example.com')
        db.add(tenant)
        db.flush()
    admin = db.scalar(select(UserModel).where(UserModel.email == email))
    if admin is not None and admin.tenant_id != tenant.id:
        raise ValueError('El correo de demostración está ocupado por otra empresa.')
    if admin is None:
        db.add(UserModel(tenant_id=tenant.id, email=email, first_name='Admin', last_name='Urbano', password_hash=PasswordHasher().hash(password), roles=[role], is_verified=True))
    if db.scalar(select(SubscriptionModel.id).where(SubscriptionModel.tenant_id == tenant.id, SubscriptionModel.closed_at.is_(None))) is None:
        db.add(SubscriptionModel(tenant_id=tenant.id, plan_id=plan.id, start_date=date.today(), end_date=date.today()+timedelta(days=29), status='ACTIVA'))
    city = db.scalar(select(CityModel).where(CityModel.name == 'Santa Cruz Demo'))
    if city is None:
        city = CityModel(name='Santa Cruz Demo', department='Santa Cruz')
        db.add(city)
        db.flush()
    if db.scalar(select(BranchModel.id).where(BranchModel.tenant_id == tenant.id, BranchModel.code == 'SC-01')) is None:
        db.add(BranchModel(tenant_id=tenant.id, code='SC-01', name='Centro Demo', city_id=city.id, address='Dirección sintética de demostración'))
    category = db.scalar(select(CategoryModel).where(CategoryModel.slug == 'demo'))
    if category is None:
        category = CategoryModel(name='Demostración', slug='demo')
        db.add(category)
        db.flush()
    if db.scalar(select(ProductModel.id).where(ProductModel.tenant_id == tenant.id, ProductModel.slug == 'prenda-demo')) is None:
        db.add(ProductModel(tenant_id=tenant.id, name='Prenda Urbano Demo', slug='prenda-demo', description='Prenda sintética para demostrar aislamiento.', category_id=category.id, base_price=150))
    db.commit()
    return tenant

def main():
    from src.infrastructure.config.settings import settings
    from sqlalchemy.engine import make_url
    if make_url(settings.database_url).host not in (None, 'localhost', '127.0.0.1', '::1'):
        raise ValueError('Este script de demostración solo admite una base local.')
    password = os.environ.get('DEMO_ADMIN_PASSWORD')
    if not password:
        raise ValueError('Define DEMO_ADMIN_PASSWORD antes de ejecutar el script.')
    from src.infrastructure.database.session import SessionLocal
    with SessionLocal() as db:
        sembrar(db, password)
    print('Empresa de demostración preparada sin duplicados.')

if __name__ == '__main__':
    main()
