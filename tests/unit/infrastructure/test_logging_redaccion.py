import json
import logging
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from src.infrastructure.observability.logging import JsonFormatter, RedactFilter, redact
from src.main import create_app


def test_credenciales_y_correos_no_se_registran():
    record = logging.LogRecord('app', logging.ERROR, '', 0,
        'Authorization: Bearer secreto-largo password="clave-compuesta valor" email=persona@example.test url=postgresql://user:clave@host/db', (), None)
    assert RedactFilter().filter(record)
    formatted = JsonFormatter().format(record)
    for value in ('secreto-largo', 'clave-compuesta', 'persona@example.test', 'user:clave', 'Authorization'):
        assert value not in formatted
    assert 'pe***@example.test' in formatted
    assert json.loads(formatted)['logger'] == 'app'


def test_excepciones_no_incluyen_parametros_sql_o_body():
    try:
        raise RuntimeError('dato-personal-no-visible')
    except RuntimeError:
        import sys
        record = logging.LogRecord('db', logging.ERROR, '', 0, 'database_failed', (), sys.exc_info())
    result = JsonFormatter().format(record)
    assert 'dato-personal-no-visible' not in result
    assert json.loads(result)['exception_type'] == 'RuntimeError'


def test_request_id_se_conserva_y_no_incluye_query(caplog):
    rid = 'c8e16fbd-7de4-40b4-af62-a529a80f0de1'
    with caplog.at_level(logging.INFO, logger='fashionstore.access'):
        response = TestClient(create_app()).get('/api/v1/no-existe?token=no-registar', headers={'X-Request-ID': rid})
    assert response.headers['X-Request-ID'] == rid
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    records = [r for r in caplog.records if r.name == 'fashionstore.access']
    assert records[-1].request_id == rid
    assert records[-1].ruta == '<unmatched>'
    assert 'no-registar' not in JsonFormatter().format(records[-1])


@pytest.mark.parametrize('value', ['persona@example.test', 'no-spaces-but-arbitrary', 'x'*500])
def test_request_id_no_es_canal_de_inyeccion(value):
    response = TestClient(create_app()).get('/health', headers={'X-Request-ID': value})
    assert response.headers['X-Request-ID'] != value
    assert UUID(response.headers['X-Request-ID'])


def test_ready_no_expone_credenciales_si_base_no_disponible():
    response = TestClient(create_app()).get('/health/ready')
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'not_ready'
    assert 'postgresql' not in response.text
    assert response.headers['X-Request-ID']
