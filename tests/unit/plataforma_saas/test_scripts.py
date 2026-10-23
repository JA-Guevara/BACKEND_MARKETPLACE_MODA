from sqlalchemy import func, select
from scripts.crear_admin_plataforma import crear
from scripts.seed_empresas_demo import sembrar
from src.auth.infrastructure.persistence.models.user import UserModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel

def test_scripts_idempotentes_y_sin_escalar_cuenta_empresa(world):
    password = 'Otra_Clave2026!Segura'
    first = crear(world.db, 'plataforma@example.com', password)
    assert crear(world.db, 'plataforma@example.com', password).id == first.id
    assert first.tenant_id is None
    import pytest
    with pytest.raises(ValueError, match='cuenta de empresa'):
        crear(world.db, 'admin0@example.com', password)
    first_tenant = sembrar(world.db, password)
    assert sembrar(world.db, password).id == first_tenant.id
    assert world.db.scalar(select(func.count()).select_from(TenantModel).where(TenantModel.slug == 'urbano')) == 1
    assert world.db.scalar(select(func.count()).select_from(UserModel).where(UserModel.email == 'admin.urbano@example.com')) == 1
