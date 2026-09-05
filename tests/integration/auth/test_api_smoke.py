from fastapi.testclient import TestClient

from src.main import app


def test_health_endpoint() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_exposes_auth_and_administration_routes() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/users" in paths
    assert "/api/v1/roles" in paths
    assert "/api/v1/audit-log" in paths
    assert "/api/v1/catalog/products" in paths
    assert "/api/v1/catalog/admin/products" in paths
    assert "/api/v1/organization/suppliers" in paths
    assert "/api/v1/organization/branches" in paths


def test_validation_errors_use_the_shared_envelope() -> None:
    response = TestClient(app).post("/api/v1/auth/login", json={})
    assert response.status_code == 422
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "validation_error"
