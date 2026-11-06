from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from pydantic import SecretStr
import pytest

from src.infrastructure.config.settings import Settings, settings
from src.plataforma_saas.application.ops_service import OpsService


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "backup_report_token", SecretStr("no-publicar-token-ficticio"))
    monkeypatch.setattr(settings, "sentry_dsn", None)
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "database_url", "postgresql://usuario:no-publicar-clave@127.0.0.1/local")
    monkeypatch.setattr(settings, "production_db_host", "db.prod-ficticio.supabase.co")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    monkeypatch.delenv("MIGRACION_SIN_RESPALDO_AUTORIZADA", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    monkeypatch.delenv("SIGNUP_ENABLED", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(settings, "stripe_secret_key", "no-publicar-clave-stripe-ficticia")
    ops = OpsService(SimpleNamespace())
    monkeypatch.setattr(ops, "_rol_salta_rls", lambda: False)
    monkeypatch.setattr(ops, "ultimo_verificado", lambda *a, **kw: SimpleNamespace(
        finished_at=datetime.now(timezone.utc) - timedelta(hours=2),
    ))
    return ops


def checks(service):
    result = service.config_checks()
    assert all(set(item) == {"code", "level", "message"} for item in result)
    return {item["code"]: item for item in result}


def test_production_sin_token_de_reporte_avisa(service, monkeypatch):
    monkeypatch.setattr(settings, "backup_report_token", None)
    assert checks(service)["backup_report_token_missing"]["level"] == "warning"


def test_production_sin_proxy_confiable_avisa(service, monkeypatch):
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    assert checks(service)["forwarded_ips_untrusted"]["level"] == "warning"


def test_excepcion_definida_es_error_hasta_que_se_retire(service, monkeypatch):
    monkeypatch.setenv("MIGRACION_SIN_RESPALDO_AUTORIZADA", "2026-11-05")
    assert checks(service)["migration_exception_active"]["level"] == "error"


def test_copia_ausente_o_mayor_26h_avisa(service, monkeypatch):
    for backup in (None, SimpleNamespace(finished_at=datetime.now(timezone.utc) - timedelta(hours=27))):
        monkeypatch.setattr(service, "ultimo_verificado", lambda *a, value=backup, **kw: value)
        assert checks(service)["backup_stale"]["level"] == "warning"


def test_configuracion_correcta_solo_informa_sentry_opcional(service):
    assert list(checks(service)) == ["sentry_missing"]
    assert checks(service)["sentry_missing"]["level"] == "info"


def test_no_publica_valores_y_detecta_ambiente_no_productivo(service, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "local")
    monkeypatch.setattr(settings, "database_url", "postgresql://usuario:no-publicar-clave@db.prod-ficticio.supabase.co/real")
    monkeypatch.setenv("MIGRACION_SIN_RESPALDO_AUTORIZADA", "2099-12-31")
    result = service.config_checks()
    assert any(item["code"] == "app_env_not_production" and item["level"] == "error" for item in result)
    text = str(result)
    for value in ("no-publicar-token-ficticio", "no-publicar-clave", "2099-12-31", "db.prod-ficticio.supabase.co"):
        assert value not in text


def test_orden_y_workers_multiples(service, monkeypatch):
    monkeypatch.setattr(settings, "backup_report_token", None)
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    result = service.config_checks()
    assert checks(service)["workers_multiple"]["level"] == "error"
    priorities = {"error": 0, "warning": 1, "info": 2}
    levels = [priorities[item["level"]] for item in result]
    assert levels == sorted(levels)


def test_arranque_local_remoto_nombra_app_env_production_sin_url():
    with pytest.raises((ValueError, RuntimeError)) as error:
        Settings(_env_file=None, app_env="local", database_url="postgresql://usuario:no-publicar-clave@db.ficticia.example/base")
    text = str(error.value)
    assert "APP_ENV=production" in text
    assert "postgresql://" not in text
    assert "no-publicar-clave" not in text


def test_alta_abierta_y_stripe_ausente_solo_informan(service, monkeypatch):
    monkeypatch.setenv("SIGNUP_ENABLED", "true")
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    result = checks(service)
    assert result["signup_enabled"]["level"] == "info"
    assert result["stripe_not_configured"]["level"] == "info"
    assert "no-publicar" not in str(result)


def test_rol_que_salta_rls_es_advertencia(service, monkeypatch):
    monkeypatch.setattr(service, "_rol_salta_rls", lambda: True)
    assert checks(service)["rls_role_bypass"]["level"] == "warning"


def test_rol_rls_no_consulta_pg_fuera_de_postgresql():
    sqlite = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    assert OpsService(sqlite)._rol_salta_rls() is False
