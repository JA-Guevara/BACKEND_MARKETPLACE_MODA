from fastapi.testclient import TestClient
import pytest

from src.infrastructure.config.settings import settings
from src.main import create_app


@pytest.mark.parametrize('environment', ['local', 'staging', 'production'])
def test_cabeceras_en_salud_y_errores(monkeypatch, environment):
    monkeypatch.setattr(settings, 'app_env', environment)
    client = TestClient(create_app())
    for path in ['/health', '/api/v1/auth/no-existe', '/api/v1/platform/no-existe']:
        r = client.get(path)
        assert r.headers['X-Content-Type-Options'] == 'nosniff'
        assert r.headers['X-Frame-Options'] == 'DENY'
        assert 'microphone=()' in r.headers['Permissions-Policy']
        assert ('Strict-Transport-Security' in r.headers) == (environment == 'production')
        if '/auth/' in path or '/platform/' in path:
            assert r.headers['Cache-Control'] == 'no-store'
