"""Regresión H1: inventario real de rutas, sin ejecutar IA ni consultar una BD."""
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest
from starlette.responses import JSONResponse

from src.auth.infrastructure.security.jwt_service import JWTService
from src.infrastructure.config.settings import settings
from src.infrastructure.security.rate_limit import RateLimiter
from src.main import create_app


@pytest.fixture
def actual_app(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    app = create_app()

    async def harmless_endpoint(scope, receive, send):
        await JSONResponse({"ok": True})(scope, receive, send)

    # Se conserva APIRoute/path/method del router real. Solo se sustituye su
    # ejecución final para no invocar proveedores IA, autenticación ni BD.
    for route in app.routes:
        if isinstance(route, APIRoute):
            route.app = harmless_endpoint
    return app


def path(app, suffix, method="POST"):
    matches = [r.path for r in app.routes if isinstance(r, APIRoute) and r.path.endswith(suffix) and method in r.methods]
    assert len(matches) == 1, (suffix, matches)
    return matches[0]


def headers(tenant="empresa-a", user="usuario-a"):
    token, _ = JWTService().create_access_token(user, tenant)
    return {"Authorization": f"Bearer {token}"}


def test_21_interpretaciones_reales_agotan_ia(actual_app):
    client = TestClient(actual_app)
    url = path(actual_app, "/analytics/ai-reports/interpret")
    for _ in range(20):
        assert client.post(url, json={}, headers=headers()).status_code == 200
    response = client.post(url, json={}, headers=headers())
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert actual_app.state.rate_limited_by_policy["ai_tenant"] == 1


def test_asistentes_comparten_cuota_por_empresa(actual_app):
    client = TestClient(actual_app)
    analytics = path(actual_app, "/analytics/assistant/interpret")
    commerce = path(actual_app, "/commerce/assistant")
    for _ in range(10):
        assert client.post(analytics, json={}, headers=headers()).status_code == 200
        assert client.post(commerce, json={}, headers=headers()).status_code == 200
    assert client.post(commerce, json={}, headers=headers()).status_code == 429


def test_voz_limita_usuario_y_empresa(actual_app):
    client = TestClient(actual_app)
    url = path(actual_app, "/commerce/assistant/transcribe")
    for _ in range(5):
        assert client.post(url, headers=headers()).status_code == 200
    assert client.post(url, headers=headers()).status_code == 429
    # Otro usuario de la misma empresa conserva las otras cinco peticiones.
    for _ in range(5):
        assert client.post(url, headers=headers(user="usuario-b")).status_code == 200
    assert client.post(url, headers=headers(user="usuario-c")).status_code == 429
    assert client.post(url, headers=headers(tenant="empresa-b", user="usuario-c")).status_code == 200


def test_empresa_b_y_get_historial_no_consumen_cuota_de_a(actual_app):
    client = TestClient(actual_app)
    url = path(actual_app, "/analytics/ai-reports/interpret")
    for _ in range(20):
        client.post(url, json={}, headers=headers())
    assert client.post(url, json={}, headers=headers()).status_code == 429
    assert client.post(url, json={}, headers=headers(tenant="empresa-b")).status_code == 200
    for suffix in ("/analytics/ai-reports/definitions", "/analytics/ai-reports/history"):
        assert client.get(path(actual_app, suffix, "GET"), headers=headers()).status_code == 200


def test_export_multiple_y_csv_comparten_cuota_empresa(actual_app):
    client = TestClient(actual_app)
    multiple = path(actual_app, "/analytics/reports/export-multiple")
    csv = path(actual_app, "/tenant/devices/export.csv", "GET")
    for _ in range(5):
        assert client.post(multiple, json={}, headers=headers()).status_code == 200
        assert client.get(csv, headers=headers()).status_code == 200
    assert client.get(csv, headers=headers()).status_code == 429
    assert actual_app.state.rate_limited_by_policy["export_tenant"] == 1


def test_inventario_de_rutas_costosas_nunca_queda_sin_politica(actual_app, monkeypatch):
    observed = []

    def permit(self, key, policy):
        observed.append(policy.nombre)
        return True, 100, 0

    monkeypatch.setattr(RateLimiter, "permitir", permit)
    client = TestClient(actual_app)
    inspected = 0
    for route in actual_app.routes:
        if not isinstance(route, APIRoute):
            continue
        ai = "POST" in route.methods and any(part in route.path for part in ("assistant", "ai-reports"))
        exporting = "export" in route.path
        if not ai and not exporting:
            continue
        method = "POST" if "POST" in route.methods else "GET"
        concrete = route.path.replace("{resource}", "products")
        observed.clear()
        client.request(method, concrete, json={}, headers=headers())
        if ai:
            assert any(name in {"ai_tenant", "ai_voice"} for name in observed), route.path
        if exporting:
            assert "export_tenant" in observed, route.path
        inspected += 1
    assert inspected >= 10


def test_tenant_en_body_o_cabecera_no_cambia_la_cuota(actual_app):
    client = TestClient(actual_app)
    url = path(actual_app, "/analytics/assistant/interpret")
    for i in range(20):
        response = client.post(url, json={"tenant_id": f"ajeno-{i}"},
                               headers={**headers(), "X-Tenant-ID": f"ajeno-{i}"})
        assert response.status_code == 200
    assert client.post(url, json={"tenant_id": "otra-empresa"}, headers={**headers(), "X-Tenant-ID": "otra-empresa"}).status_code == 429
