"""El humo solo habla con una sesión HTTP simulada en estas pruebas."""
import json
from pathlib import Path

import pytest

from scripts import verificar_despliegue as smoke


FIXTURES = Path(__file__).resolve().parents[3] / "docs/PS-correcciones-liberacion/contrato/fixtures"
HEADERS = {"X-App-Env": "production", "X-Content-Type-Options": "nosniff"}


def fixture(name):
    if FIXTURES.is_dir():
        return json.loads((FIXTURES / (name + ".json")).read_text(encoding="utf-8"))
    if name == "health_ready":
        return {"status": "ready", "revision": "20261110_0035", "version": "1.0.0"}
    if name == "login_humo":
        return {"email": "humo-limite@fashionstore.invalid", "password": "no-es-una-cuenta"}
    if name == "login_429":
        return {"success": False, "error": {"code": "rate_limited"}}
    if name == "ops_status_ok":
        return {"success": True, "data": {"config_checks": []}}
    raise AssertionError(name)


class Response:
    def __init__(self, status, body, headers=None):
        self.status_code, self.body = status, body
        self.headers = {**HEADERS, **(headers or {})}

    def json(self):
        return self.body


class Session:
    def __init__(self, *, revision=None, omit_header=None, final_login=429):
        self.headers = {}
        self.revision = revision
        self.omit_header = omit_header
        self.final_login = final_login
        self.login_calls = 0
        self.status_authorizations = []

    def get(self, url, **kwargs):
        if url.endswith('/health/ready'):
            body = fixture('health_ready')
            if self.revision:
                body['revision'] = self.revision
            result = Response(200, body)
        elif url.endswith('/health'):
            result = Response(200, {'status': 'ok'})
        elif url.endswith('/platform/ops/status'):
            self.status_authorizations.append(kwargs.get('headers', {}).get('Authorization'))
            result = Response(200, fixture('ops_status_ok'))
        else:
            result = Response(401, {'success': False})
        if self.omit_header:
            result.headers.pop(self.omit_header, None)
        return result

    def post(self, url, **kwargs):
        assert url.endswith('/api/v1/auth/login')
        assert kwargs['json'] == fixture('login_humo')
        assert 'Authorization' not in kwargs.get('headers', {})
        self.login_calls += 1
        status = self.final_login if self.login_calls == 6 else 401
        return Response(status, fixture('login_429') if status == 429 else {'success': False},
                        {'Retry-After': '52', 'X-RateLimit-Limit': '5', 'X-RateLimit-Remaining': '0'})

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def run(monkeypatch, session, extra=None):
    monkeypatch.setattr(smoke.requests, 'Session', lambda: session)
    return smoke.main(['--base-url', 'https://api.example.invalid', '--revision-esperada', '20261110_0035', *(extra or [])])


def test_humo_correcto_termina_en_cero(monkeypatch):
    session = Session()
    assert run(monkeypatch, session) == 0
    assert session.login_calls == 6


def test_humo_rechaza_otra_revision(monkeypatch):
    assert run(monkeypatch, Session(revision='20261109_0031')) != 0


@pytest.mark.parametrize('header', ['X-App-Env', 'X-Content-Type-Options'])
def test_humo_rechaza_cabecera_ausente(monkeypatch, header):
    assert run(monkeypatch, Session(omit_header=header)) != 0


def test_humo_rechaza_sexto_login_sin_limite(monkeypatch):
    assert run(monkeypatch, Session(final_login=401)) != 0


def test_humo_no_imprime_token_y_no_lo_envia_al_login(monkeypatch, capsys):
    secret = 'token-sintetico-que-nunca-se-registra'
    monkeypatch.setenv('SMOKE_TEST_TOKEN', secret)
    session = Session()
    assert run(monkeypatch, session, ['--token-env', 'SMOKE_TEST_TOKEN']) == 0
    assert secret not in capsys.readouterr().out
    assert session.status_authorizations == ['Bearer ' + secret]
