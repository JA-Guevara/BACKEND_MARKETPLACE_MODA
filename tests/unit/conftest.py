"""Mundo SaaS local compartido por pruebas de integración entre módulos."""
import importlib.util
from pathlib import Path
import pytest

@pytest.fixture
def saas_world(monkeypatch):
    path = Path(__file__).parent / 'plataforma_saas/conftest.py'
    spec = importlib.util.spec_from_file_location('saas_test_world', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.AuthEmailService, 'send_tenant_invitation', lambda *args: False)
    world = module.create_world()
    try:
        yield world
    finally:
        world.client.close()
        world.db.close()
        world.engine.dispose()
