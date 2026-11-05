from fastapi.testclient import TestClient
from sqlalchemy import func, select

from src.auth.infrastructure.persistence.models.refresh_token import RefreshTokenModel
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.infrastructure.config.settings import settings
from src.main import create_app


def test_mantenimiento_bloquea_escrituras_y_preserva_estado_y_ops(world, monkeypatch):
    monkeypatch.setattr(settings, "maintenance_mode", True)
    response = world.client.post("/api/v1/auth/register", json={})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "maintenance"
    assert response.headers["Retry-After"] == "300"
    assert world.client.get("/health").status_code == 200
    assert world.client.get("/api/v1/auth/me", headers=world.headers(world.admin_a)).status_code == 200
    assert world.client.post("/api/v1/platform/ops/ruta-no-registrada").status_code == 404
    assert world.client.post("/api/v1/platform/ops-otra").status_code == 503


def test_mantenimiento_permite_solo_login_del_equipo_de_plataforma(world, monkeypatch):
    from conftest import TEST_PASSWORD

    monkeypatch.setattr(settings, "maintenance_mode", True)
    url = "/api/v1/auth/login"
    previous_events = world.db.scalar(select(func.count(AuditEventModel.id)))
    previous_tokens = world.db.scalar(select(func.count(RefreshTokenModel.id)))
    tenant_login = world.client.post(url, json={"email": world.admin_a.email, "password": TEST_PASSWORD})
    unknown_login = world.client.post(url, json={"email": "desconocida@example.com", "password": TEST_PASSWORD})
    invalid_login = world.client.post(url, json={})
    assert tenant_login.status_code == unknown_login.status_code == invalid_login.status_code == 503
    assert tenant_login.json() == unknown_login.json() == invalid_login.json()
    assert tenant_login.headers["Retry-After"] == "300"
    assert world.db.scalar(select(func.count(AuditEventModel.id))) == previous_events
    assert world.db.scalar(select(func.count(RefreshTokenModel.id))) == previous_tokens
    login = world.client.post(url, json={"email": world.platform.email, "password": TEST_PASSWORD})
    assert login.status_code == 200, login.text
    assert login.json()["data"]["access_token"]


def test_web_puede_leer_retry_after_en_mantenimiento(monkeypatch):
    origin = "https://web.example.test"
    monkeypatch.setattr(settings, "cors_origins", [origin])
    monkeypatch.setattr(settings, "maintenance_mode", True)
    response = TestClient(create_app()).post(
        "/api/v1/auth/register", json={}, headers={"Origin": origin}
    )
    assert response.status_code == 503
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert "Retry-After" in response.headers["Access-Control-Expose-Headers"]
