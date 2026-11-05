from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.auth.application.services.auth_service import AuthService
from src.auth.infrastructure.http.schemas import RegisterRequest
from src.auth.infrastructure.persistence.repositories.auth_token_repository import (
    AuthTokenRepository,
    extract_device_label,
    extract_ip_prefix,
)
from src.infrastructure.database.base import Base
from src.roles.infrastructure.persistence.models.role import RoleModel
from src.shared.exceptions.domain_exception import AuthenticationError


@pytest.fixture(autouse=True)
def isolate_email(monkeypatch):
    monkeypatch.setattr(
        "src.auth.infrastructure.email.smtp_sender.SMTPEmailSender.send",
        lambda *args, **kwargs: True,
    )


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    session.add(RoleModel(code="client", name="Cliente", is_system=True, is_active=True))
    session.add(RoleModel(code="admin", name="Administrador", is_system=True, is_active=True))
    session.commit()
    return session


def test_device_and_ip_parsing() -> None:
    assert extract_ip_prefix("190.186.20.45") == "190.186.20.0/24"
    assert "Windows" in extract_device_label("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    assert "Android" in extract_device_label("Mozilla/5.0 (Linux; Android 14)")


def test_lista_solo_las_propias() -> None:
    db = make_session()
    service = AuthService(db)
    u1 = service.register(
        RegisterRequest(
            email="u1@example.com",
            password="RopaSegura!2026",
            first_name="Usuario",
            last_name="Uno",
        ),
        ip_address="190.186.20.10",
        user_agent="Mozilla/5.0 (Windows NT 10.0)",
    )
    u2 = service.register(
        RegisterRequest(
            email="u2@example.com",
            password="RopaSegura!2026",
            first_name="Usuario",
            last_name="Dos",
        ),
        ip_address="190.186.20.20",
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)",
    )

    t1 = service.login("u1@example.com", "RopaSegura!2026", ip_address="190.186.20.10", user_agent="Windows")
    t2 = service.login("u2@example.com", "RopaSegura!2026", ip_address="190.186.20.20", user_agent="iPhone")

    repo = AuthTokenRepository(db)
    sessions_u1 = repo.listar_activas(u1.id)
    sessions_u2 = repo.listar_activas(u2.id)

    assert len(sessions_u1) == 1
    assert sessions_u1[0].user_id == u1.id
    assert sessions_u1[0].ip_prefix == "190.186.20.0/24"

    assert len(sessions_u2) == 1
    assert sessions_u2[0].user_id == u2.id


def test_revoke_others_conserva_la_actual() -> None:
    db = make_session()
    service = AuthService(db)
    u1 = service.register(
        RegisterRequest(
            email="multi@example.com",
            password="RopaSegura!2026",
            first_name="Multi",
            last_name="Sesion",
        ),
        ip_address="190.186.20.10",
        user_agent="Device1",
    )

    t1 = service.login("multi@example.com", "RopaSegura!2026", ip_address="190.186.20.1", user_agent="Chrome")
    t2 = service.login("multi@example.com", "RopaSegura!2026", ip_address="190.186.20.2", user_agent="Firefox")
    t3 = service.login("multi@example.com", "RopaSegura!2026", ip_address="190.186.20.3", user_agent="Edge")

    repo = AuthTokenRepository(db)
    activas_antes = repo.listar_activas(u1.id)
    assert len(activas_antes) == 3

    p3 = service.jwt.decode(t3.refresh_token, "refresh")
    current_jti = p3["jti"]

    revoked_count = repo.revocar_otras(u1.id, current_jti)
    db.commit()
    assert revoked_count == 2

    activas_despues = repo.listar_activas(u1.id)
    assert len(activas_despues) == 1
    assert activas_despues[0].jti == current_jti


def test_inactividad_revoca_sesion() -> None:
    db = make_session()
    service = AuthService(db)
    u = service.register(
        RegisterRequest(
            email="admin@example.com",
            password="RopaSegura!2026",
            first_name="Admin",
            last_name="Test",
        ),
        ip_address="190.186.20.1",
        user_agent="Chrome",
    )
    admin_role = service.roles.get_role_by_code("admin")
    u.roles.append(admin_role)
    db.commit()

    t = service.login("admin@example.com", "RopaSegura!2026", ip_address="190.186.20.1", user_agent="Chrome")
    p = service.jwt.decode(t.refresh_token, "refresh")

    repo = AuthTokenRepository(db)
    stored = repo.get_refresh(p["jti"])
    assert stored is not None

    # Simular inactividad de 35 minutos para rol admin (limite default = 30 min)
    stored.last_used_at = datetime.now(timezone.utc) - timedelta(minutes=35)
    db.commit()

    with pytest.raises(AuthenticationError, match="inactividad"):
        service.refresh(t.refresh_token, ip_address="190.186.20.1")

    db.refresh(stored)
    assert stored.revoked_at is not None


def test_cambio_de_contrasena_cierra_las_demas() -> None:
    db = make_session()
    service = AuthService(db)
    u = service.register(
        RegisterRequest(
            email="pwd@example.com",
            password="RopaSegura!2026",
            first_name="Pwd",
            last_name="Change",
        ),
        ip_address="190.186.20.1",
        user_agent="Chrome",
    )

    t1 = service.login("pwd@example.com", "RopaSegura!2026", ip_address="190.186.20.1", user_agent="Device A")
    t2 = service.login("pwd@example.com", "RopaSegura!2026", ip_address="190.186.20.2", user_agent="Device B")

    repo = AuthTokenRepository(db)
    assert len(repo.listar_activas(u.id)) == 2

    service.change_password(u, "RopaSegura!2026", "NuevaContrasena!2026")

    assert len(repo.listar_activas(u.id)) == 0
