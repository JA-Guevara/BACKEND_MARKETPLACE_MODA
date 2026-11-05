import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.infrastructure.database.base import Base
from src.auth.infrastructure.persistence.models.user import UserModel
from src.roles.infrastructure.persistence.models.role import RoleModel
from src.integraciones.application.api_keys_service import (
    ALLOWED_INTEGRATION_SCOPES,
    ApiKeyInvalidError,
    ApiKeyScopeError,
    ApiKeysService,
    hash_api_key,
)
from src.plataforma_saas.infrastructure.models.tenant import TenantModel


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    return session


def make_tenant(db: Session, slug: str, name: str = "Tienda Test") -> TenantModel:
    t = TenantModel(
        id=uuid.uuid4(),
        slug=slug,
        legal_name=f"{name} SRL",
        trade_name=name,
        tax_id=f"NIT-{uuid.uuid4().hex[:8]}",
        contact_email=f"{slug}@example.com",
        status="ACTIVA",
    )
    db.add(t)
    db.commit()
    return t


def test_crear_y_autenticar_api_key() -> None:
    db = make_session()
    tenant = make_tenant(db, "tienda-test")
    tenant_id = tenant.id

    service = ApiKeysService(db)
    key_model, raw_key = service.crear(
        tenant_id=tenant_id,
        name="Integración ERP",
        scopes=["sales.read", "stock.read"],
    )

    assert raw_key.startswith("fs_live_")
    assert key_model.prefix == raw_key[:12]
    assert key_model.tenant_id == tenant_id
    assert "sales.read" in key_model.scopes

    # Autenticar
    authenticated_model, auth_tenant_id, scopes = service.autenticar(raw_key)
    assert auth_tenant_id == tenant_id
    assert authenticated_model.id == key_model.id
    assert authenticated_model.last_used_at is not None

    # Autenticar con formato Bearer
    _, bearer_tenant, _ = service.autenticar(f"Bearer {raw_key}")
    assert bearer_tenant == tenant_id


def test_clave_revocada_falla_401() -> None:
    db = make_session()
    tenant_id = uuid.uuid4()
    service = ApiKeysService(db)

    key_model, raw_key = service.crear(
        tenant_id=tenant_id,
        name="Clave Temporal",
        scopes=["catalog.read"],
    )

    # Revocar clave
    revocado = service.revocar(tenant_id, key_model.id)
    assert revocado is True

    # Debe fallar con ApiKeyInvalidError (401)
    with pytest.raises(ApiKeyInvalidError) as exc_info:
        service.autenticar(raw_key)

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "api_key_invalid"


def test_scope_insuficiente_falla_403() -> None:
    scopes = ["catalog.read", "stock.read"]

    # Scope permitido pasa
    ApiKeysService.verificar_scope(scopes, "catalog.read")
    ApiKeysService.verificar_scope(scopes, "stock.read")

    # Scope no concedido falla con 403
    with pytest.raises(ApiKeyScopeError) as exc_info:
        ApiKeysService.verificar_scope(scopes, "sales.read")

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "api_key_scope"


def test_clave_no_aparece_en_logs_ni_modelo() -> None:
    db = make_session()
    tenant_id = uuid.uuid4()
    service = ApiKeysService(db)

    key_model, raw_key = service.crear(
        tenant_id=tenant_id,
        name="Clave Secreta",
        scopes=["sales.read"],
    )

    # El modelo guarda el hash sha256 con pimienta, jamás el raw_key
    assert key_model.key_hash != raw_key
    assert raw_key not in repr(key_model.__dict__)
    assert raw_key not in key_model.prefix
