import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.auth.application.services.auth_service import AuthService
from src.auth.infrastructure.http.schemas import RegisterRequest
from src.infrastructure.database.base import Base
from src.roles.infrastructure.persistence.models.role import RoleModel


@pytest.fixture(autouse=True)
def isolate_email(monkeypatch):
    # Unit tests never use credentials from .env or send real verification mail.
    monkeypatch.setattr("src.auth.infrastructure.email.smtp_sender.SMTPEmailSender.send", lambda *args, **kwargs: True)


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    session.add(RoleModel(code="client", name="Cliente", is_system=True, is_active=True))
    session.commit()
    return session


def test_register_and_login_issue_tokens() -> None:
    db = make_session()
    service = AuthService(db)
    user = service.register(
        RegisterRequest(
            email="cliente@example.com",
            password="RopaSegura!2026",
            first_name="Ana",
            last_name="Flores",
        ),
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    result = service.login(
        "cliente@example.com", "RopaSegura!2026", ip_address="127.0.0.1", user_agent="pytest"
    )
    assert result.user.id == user.id
    assert result.access_token
    assert result.refresh_token


def test_email_is_normalized_on_registration() -> None:
    db = make_session()
    user = AuthService(db).register(
        RegisterRequest(
            email="CLIENTE@Example.com",
            password="RopaSegura!2026",
            first_name="Ana",
            last_name="Flores",
        ),
        ip_address=None,
        user_agent=None,
    )
    assert user.email == "cliente@example.com"


def test_cliente_multitienda_login_en_otra_empresa() -> None:
    from src.plataforma_saas.infrastructure.models.tenant import TenantModel
    import uuid

    db = make_session()
    t1 = TenantModel(id=uuid.uuid4(), slug="empresa-alfa", trade_name="FashionStore", legal_name="FS SRL", tax_id="1001", contact_email="fs@test.com", status="ACTIVA")
    t2 = TenantModel(id=uuid.uuid4(), slug="manaco", trade_name="Manaco", legal_name="Manaco SA", tax_id="1002", contact_email="manaco@test.com", status="ACTIVA")
    db.add_all([t1, t2])
    db.commit()

    # Registra en tienda 1
    s1 = AuthService(db, tenant_id=t1.id)
    u = s1.register(
        RegisterRequest(
            email="feyepez603@gmail.com",
            password="Password!2026",
            first_name="Fernando",
            last_name="Yepez",
        ),
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    assert u.tenant_id == t1.id

    # Inicia sesión en tienda 2 (Manaco) con su misma cuenta
    res = s1.login(
        "feyepez603@gmail.com",
        "Password!2026",
        ip_address="127.0.0.1",
        user_agent="pytest",
        tenant_slug="manaco",
    )
    assert res.user.tenant is not None
    assert res.user.tenant.slug == "manaco"
    assert res.access_token is not None


def test_cliente_registro_existente_en_otra_tienda_vincula_transparentemente() -> None:
    from src.plataforma_saas.infrastructure.models.tenant import TenantModel
    import uuid

    db = make_session()
    t1 = TenantModel(id=uuid.uuid4(), slug="tienda-uno", trade_name="Tienda Uno", legal_name="T1 SRL", tax_id="1003", contact_email="t1@test.com", status="ACTIVA")
    t2 = TenantModel(id=uuid.uuid4(), slug="tienda-dos", trade_name="Tienda Dos", legal_name="T2 SRL", tax_id="1004", contact_email="t2@test.com", status="ACTIVA")
    db.add_all([t1, t2])
    db.commit()

    s1 = AuthService(db, tenant_id=t1.id)
    u1 = s1.register(
        RegisterRequest(
            email="cliente.global@example.com",
            password="Password!2026",
            first_name="Carlos",
            last_name="Perez",
        ),
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    # El mismo cliente se registra en Tienda Dos con su misma contraseña
    s2 = AuthService(db, tenant_id=t2.id)
    u2 = s2.register(
        RegisterRequest(
            email="cliente.global@example.com",
            password="Password!2026",
            first_name="Carlos",
            last_name="Perez",
        ),
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    assert u2.id == u1.id
