import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from src.infrastructure.database.safety import require_environment_match


@pytest.mark.parametrize("entry", [["-c", "import src.main"], ["-m", "alembic", "upgrade", "head"]])
def test_local_bloquea_base_remota_antes_de_conectar(entry):
    env = {**os.environ, "APP_ENV": "local", "ALLOW_REMOTE_DB": "1",
           "DATABASE_URL": "postgresql://user:do-not-print@invalid.example/db"}
    result = subprocess.run([sys.executable, *entry], env=env, cwd=Path(__file__).resolve().parents[3],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert "remota bloqueada para APP_ENV=local" in result.stderr
    assert "do-not-print" not in result.stderr


def test_production_fuera_de_railway_no_arranca(monkeypatch):
    from src.infrastructure.config.settings import Settings

    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID", raising=False)
    with pytest.raises(RuntimeError, match="requiere RAILWAY_ENVIRONMENT_ID"):
        Settings(_env_file=None, app_env="production", jwt_secret_key="x" * 40)


@pytest.mark.parametrize("url", [
    "postgresql://user@db.projectprod.supabase.co/db",
    "postgresql://user.projectprod@aws-0-region.pooler.supabase.com/db",
    "postgresql://user@db.stage.example/db?host=db.projectprod.supabase.co",
])
def test_staging_rechaza_produccion_incluso_por_pooler(url):
    with pytest.raises(RuntimeError):
        require_environment_match("staging", url, "db.projectprod.supabase.co")


def test_staging_acepta_otro_proyecto_y_exige_identidad_de_produccion():
    target = "postgresql://user.projectstage@aws-0-region.pooler.supabase.com/db"
    with pytest.raises(RuntimeError, match="PRODUCTION_DB_HOST"):
        require_environment_match("staging", target)
    require_environment_match("staging", target, "db.projectprod.supabase.co")


def test_cabecera_ambiente_visible_en_cors():
    from src.infrastructure.config.settings import settings
    from src.main import create_app

    response = TestClient(create_app()).get("/health", headers={"Origin": settings.cors_origins[0]})
    assert response.status_code == 200
    assert response.headers["X-App-Env"] == settings.app_env
    assert "x-app-env" in response.headers["Access-Control-Expose-Headers"].lower()
