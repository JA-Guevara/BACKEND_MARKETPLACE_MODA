import pytest
import os
from pathlib import Path
import subprocess
import sys

from src.infrastructure.database.safety import require_local_database


@pytest.mark.parametrize("url", [
    "sqlite:///:memory:", "sqlite+pysqlite:///prueba.db",
    "postgresql://user@127.0.0.1/db", "postgresql://user@localhost/db",
    "postgresql://user@[::1]/db",
])
def test_local_database_is_allowed(monkeypatch, url):
    monkeypatch.delenv("ALLOW_REMOTE_DB", raising=False)
    require_local_database(url)


@pytest.mark.parametrize("flag", [None, "0", "true", "yes"])
@pytest.mark.parametrize("url", [
    "postgresql://user:secret@db.example.com/db",
    "postgresql://user@192.168.1.10/db",
    "postgresql://user@localhost/db?host=remote.example.com",
    "postgresql:///db?service=production", "postgresql:///db",
    "postgresql://user@localhost/db?hostaddr=8.8.8.8",
])
def test_remote_database_is_blocked_without_explicit_flag(monkeypatch, url, flag):
    if flag is None:
        monkeypatch.delenv("ALLOW_REMOTE_DB", raising=False)
    else:
        monkeypatch.setenv("ALLOW_REMOTE_DB", flag)
    with pytest.raises(RuntimeError, match="remota bloqueada") as exc:
        require_local_database(url)
    assert "secret" not in str(exc.value)
    assert url not in str(exc.value)


def test_explicit_remote_authorization(monkeypatch):
    monkeypatch.setenv("ALLOW_REMOTE_DB", "1")
    require_local_database("postgresql://user@db.example.com/db")


@pytest.mark.parametrize("key", ["PGHOSTADDR", "PGSERVICE"])
def test_libpq_environment_cannot_override_local_host(monkeypatch, key):
    monkeypatch.delenv("ALLOW_REMOTE_DB", raising=False)
    monkeypatch.setenv(key, "production")
    with pytest.raises(RuntimeError):
        require_local_database("postgresql://user@localhost/db")


@pytest.mark.parametrize("args", [
    ["-m", "alembic", "upgrade", "head"],
    ["scripts/reconciliar_produccion.py", "--aplicar"],
    ["-c", "import src.infrastructure.database.session"],
])
def test_entrypoints_reject_remote_database_before_connecting(args):
    env = {**os.environ, "DATABASE_URL": "postgresql://user:secret@invalid.example/db",
           "ALLOW_REMOTE_DB": "0", "APP_ENV": "test"}
    result = subprocess.run([sys.executable, *args], env=env,
                            cwd=Path(__file__).resolve().parents[2],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert "remota bloqueada" in result.stderr
    assert "secret" not in result.stderr
    assert "OperationalError" not in result.stderr
