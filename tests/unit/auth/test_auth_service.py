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
