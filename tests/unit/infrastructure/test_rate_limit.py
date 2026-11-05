from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from src.auth.infrastructure.security.jwt_service import JWTService
from src.infrastructure.config.settings import settings
from src.infrastructure.http.security_headers import SecurityHeadersMiddleware
from src.infrastructure.security.rate_limit import Politica, RateLimiter, RateLimitMiddleware


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    @app.api_route('/{path:path}', methods=['GET', 'POST'])
    async def echo(path: str, request: Request):
        return await request.json() if request.method == 'POST' else {'ok': True}

    return TestClient(app)


def test_sexto_login_limitado_y_cuerpo_no_se_pierde(client):
    for _ in range(5):
        r = client.post('/api/v1/auth/login', json={'email': 'ejemplo@example.test', 'password': 'no-registrar'})
        assert r.status_code == 200
        assert r.json()['password'] == 'no-registrar'
    r = client.post('/api/v1/auth/login', json={'email': 'EJEMPLO@example.test'})
    assert r.status_code == 429
    assert 1 <= int(r.headers['Retry-After']) <= 60
    assert r.headers['X-RateLimit-Remaining'] == '0'
    assert r.headers['Cache-Control'] == 'no-store'
    assert r.json()['error']['code'] == 'rate_limited'
    assert client.app.state.rate_limited_by_policy['login_email_ip'] == 1


def test_limite_ip_no_se_evade_rotando_correos(client):
    for i in range(20):
        assert client.post('/api/v1/auth/login', json={'email': f'user{i}@example.test'}).status_code == 200
    assert client.post('/api/v1/auth/login', json={'email': 'otro@example.test'}).status_code == 429


def test_empresa_b_conserva_su_cuota_y_tokens_falsos_no_la_consumen(client):
    a, _ = JWTService().create_access_token('user-a', 'empresa-a')
    b, _ = JWTService().create_access_token('user-b', 'empresa-b')
    path = '/api/v1/analytics/ai-reports/interpret'
    for _ in range(20):
        assert client.post(path, json={}, headers={'Authorization': f'Bearer {a}'}).status_code == 200
    assert client.post(path, json={}, headers={'Authorization': f'Bearer {a}'}).status_code == 429
    assert client.post(path, json={}, headers={'Authorization': f'Bearer {b}'}).status_code == 200


def test_salud_y_reportes_de_copia_nunca_se_limitan(client):
    for _ in range(310):
        assert client.get('/health').status_code == 200
        assert client.post('/api/v1/platform/ops/backups', json={}).status_code == 200
    assert client.get('/health/ready').status_code == 200


def test_ventana_deslizante_y_concurrencia():
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0])
    policy = Politica('test', 5, 60)
    with ThreadPoolExecutor(max_workers=10) as pool:
        allowed = list(pool.map(lambda _: limiter.permitir('key', policy)[0], range(30)))
    assert sum(allowed) == 5
    now[0] = 60.0
    assert limiter.permitir('key', policy) == (True, 4, 0)


def test_memoria_acotada_sin_borrar_cuotas_activas():
    limiter = RateLimiter(max_keys=2)
    policy = Politica('test', 1, 60)
    assert limiter.permitir('a', policy)[0]
    assert limiter.permitir('b', policy)[0]
    assert not limiter.permitir('c', policy)[0]
    assert not limiter.permitir('a', policy)[0]
