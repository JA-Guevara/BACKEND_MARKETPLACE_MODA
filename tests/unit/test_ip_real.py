"""H2: el proxy solo cambia la IP cuando Uvicorn confía en ese origen."""
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from scripts import iniciar_servidor, railway_entrypoint
from src.infrastructure.config.settings import settings
from src.infrastructure.security.rate_limit import RateLimitMiddleware


def capture_start(monkeypatch, forwarded=None):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "entorno-ficticio")
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    if forwarded is None:
        monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    else:
        monkeypatch.setenv("FORWARDED_ALLOW_IPS", forwarded)
    monkeypatch.setattr(iniciar_servidor.os, "chdir", Mock())
    monkeypatch.setattr(railway_entrypoint, "preparar", Mock())
    run = Mock()
    monkeypatch.setattr(iniciar_servidor.os, "execv", run)
    iniciar_servidor.main()
    return run.call_args.args[1]


def test_arranque_railway_declara_proxy_y_origenes_configurados(monkeypatch):
    command = capture_start(monkeypatch, "10.0.0.0/8")
    assert "--proxy-headers" in command
    assert command[command.index("--forwarded-allow-ips") + 1] == "10.0.0.0/8"


def test_arranque_no_confia_en_todos_los_proxies_por_defecto(monkeypatch):
    command = capture_start(monkeypatch)
    assert command[command.index("--forwarded-allow-ips") + 1] == "127.0.0.1"


def proxy_client(monkeypatch, trusted_hosts):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.post("/api/v1/auth/login")
    async def login():
        return {"ok": True}

    return TestClient(ProxyHeadersMiddleware(app, trusted_hosts=trusted_hosts))


def test_proxy_confiable_separa_las_cuotas_de_dos_clientes(monkeypatch):
    client = proxy_client(monkeypatch, ["testclient"])
    for i in range(20):
        assert client.post("/api/v1/auth/login", json={"email": f"a{i}@example.com"},
                           headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": "extra@example.com"},
                       headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 429
    assert client.post("/api/v1/auth/login", json={"email": "b@example.com"},
                       headers={"X-Forwarded-For": "203.0.113.20"}).status_code == 200


def test_proxy_no_confiable_ignora_la_cabecera_del_cliente(monkeypatch):
    client = proxy_client(monkeypatch, ["127.0.0.1"])
    for i in range(20):
        assert client.post("/api/v1/auth/login", json={"email": f"a{i}@example.com"},
                           headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": "b@example.com"},
                       headers={"X-Forwarded-For": "203.0.113.20"}).status_code == 429


def test_varios_workers_con_limitador_local_fallan_explicitamente(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "entorno-ficticio")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(iniciar_servidor.os, "chdir", Mock())
    prepare = Mock()
    execute = Mock()
    monkeypatch.setattr(railway_entrypoint, "preparar", prepare)
    monkeypatch.setattr(iniciar_servidor.os, "execv", execute)
    with pytest.raises((RuntimeError, ValueError), match="config_invalid.*WEB_CONCURRENCY"):
        iniciar_servidor.main()
    prepare.assert_not_called()
    execute.assert_not_called()
