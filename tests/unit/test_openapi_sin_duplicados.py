from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select

from src.main import create_app
from src.plataforma_saas.infrastructure.models.module import TenantLimitModel


def test_openapi_no_tiene_operaciones_duplicadas():
    app = create_app()
    operations = Counter((method, route.path) for route in app.routes
                         for method in getattr(route, "methods", set()))
    assert not {operation: count for operation, count in operations.items() if count > 1}
    operation_ids = [operation["operationId"] for path in app.openapi()["paths"].values()
                     for operation in path.values() if isinstance(operation, dict) and "operationId" in operation]
    assert len(operation_ids) == len(set(operation_ids))


def test_alembic_tiene_una_sola_cabeza():
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1


def test_limites_get_informa_plan_uso_override_y_vencimiento_sin_mezclar_empresas(saas_world):
    world = saas_world
    tenant = world.tenants[0]
    other = world.tenants[1]
    world.db.add(TenantLimitModel(tenant_id=tenant.id, limit_code="max_active_branches", value=7,
        reason="Cupo de prueba", expires_at=datetime.now(timezone.utc)+timedelta(days=1)))
    world.db.commit()
    path = f"/api/v1/platform/tenants/{tenant.id}/limits"
    assert world.client.get(path, headers=world.headers(world.admins[0])).status_code == 403
    assert world.client.get(path, headers=world.headers(world.admins[1])).status_code == 403
    result = world.client.get(path, headers=world.headers(world.platform))
    assert result.status_code == 200, result.text
    limit = result.json()["data"][0]
    assert (limit["plan_value"], limit["effective_value"], limit["usage"], limit["source"]) == (2, 7, 1, "EMPRESA")
    assert limit["override_active"] is True
    assert limit["override"]["reason"] == "Cupo de prueba"
    assert limit["subscription_end_date"]
    other_result = world.client.get(f"/api/v1/platform/tenants/{other.id}/limits", headers=world.headers(world.platform))
    assert other_result.json()["data"][0]["override"] is None
    assert other_result.json()["data"][0]["effective_value"] == 10
    override = world.db.scalar(select(TenantLimitModel).where(TenantLimitModel.tenant_id == tenant.id))
    override.expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
    world.db.commit()
    expired = world.client.get(path, headers=world.headers(world.platform)).json()["data"][0]
    assert (expired["effective_value"], expired["source"], expired["override_active"]) == (2, "PLAN", False)
    assert expired["override"]["reason"] == "Cupo de prueba"
    assert world.client.get(f"/api/v1/platform/tenants/{uuid4()}/limits", headers=world.headers(world.platform)).status_code == 404
