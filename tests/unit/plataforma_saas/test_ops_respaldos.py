from datetime import datetime, timedelta, timezone

import httpx
from pydantic import SecretStr
import pytest
from sqlalchemy import func, select

from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.infrastructure.config.settings import settings
from src.plataforma_saas.application.ops_service import OpsService
from src.plataforma_saas.infrastructure.models.ops import PlatformBackup
from src.roles.infrastructure.persistence.models.permission import PermissionModel


BASE = "/api/v1/platform/ops"
REVISION = "20261109_0031"
SERVICE_HEADERS = {"Authorization": "Bearer token-local-para-pruebas"}


@pytest.fixture(autouse=True)
def configurar_token_servicio(monkeypatch):
    monkeypatch.setattr(settings, "backup_report_token", SecretStr("token-local-para-pruebas"))


@pytest.fixture
def reporte():
    now = datetime.now(timezone.utc)
    return {
        "kind": "manual",
        "started_at": (now - timedelta(minutes=2)).isoformat(),
        "finished_at": (now - timedelta(minutes=1)).isoformat(),
        "size_bytes": 2048,
        "sha256": "c" * 64,
        "storage_ref": "artifact:bd-20261105-manual",
        "alembic_revision": REVISION,
        "pg_server_version": 180006,
        "verify_status": "ok",
        "verify_report": {
            "ok": True,
            "duration_seconds": 17.5,
            "alembic_revision": REVISION,
            "checks": [
                {"name": "revision", "ok": True, "details": {"expected": REVISION, "actual": REVISION, "count": 1}},
                {"name": "tablas_clave", "ok": True, "details": {"tenants": 2, "users": 4, "products": 2, "permissions": 59}},
                {"name": "permisos", "ok": True, "details": {"expected": 59, "missing": 0, "extra": 0, "wrong_id": 0}},
                {"name": "esquema", "ok": True, "details": {"missing": 0, "extra": 0}},
            ],
        },
        "workflow_run_url": "https://github.com/example/marketplace/actions/runs/123/attempts/1",
    }


def _permitir(world, code):
    world.platform_role.permissions.append(PermissionModel(code=code, name=code, module="platform", scope="platform"))
    world.db.commit()


def test_token_servicio_invalido_y_jwt_de_plataforma_no_pueden_reportar(saas_world, reporte):
    world = saas_world
    _permitir(world, "platform.ops.write")
    for headers in ({}, {"Authorization": "Bearer inválido"}, world.headers(world.platform)):
        # En HTTP los valores de cabecera admitidos aquí son bytes ASCII.
        auth = {key: value.encode() for key, value in headers.items()}
        response = world.client.post(f"{BASE}/backups", headers=auth, json=reporte)
        assert response.status_code == 401, response.text
    assert world.db.scalar(select(func.count()).select_from(PlatformBackup)) == 0


def test_registro_idempotente_y_listado_por_permiso(saas_world, reporte):
    world = saas_world
    first = world.client.post(f"{BASE}/backups", headers=SERVICE_HEADERS, json=reporte)
    second = world.client.post(f"{BASE}/backups", headers=SERVICE_HEADERS, json=reporte)
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert world.db.scalar(select(func.count()).select_from(PlatformBackup)) == 1
    assert world.client.get(f"{BASE}/backups", headers=SERVICE_HEADERS).status_code == 401
    assert world.client.get(f"{BASE}/status", headers=world.headers(world.platform)).status_code == 403

    _permitir(world, "platform.ops.read")
    listado = world.client.get(f"{BASE}/backups", headers=world.headers(world.platform))
    assert listado.status_code == 200, listado.text
    assert listado.json()["data"]["total"] == 1
    estado = world.client.get(f"{BASE}/status", headers=world.headers(world.platform))
    assert estado.status_code == 200, estado.text
    assert estado.json()["data"]["ultimo_respaldo"]["alembic_revision"] == REVISION


def test_rechaza_copia_ok_sin_informe_completo_y_sin_fecha_valida(saas_world, reporte):
    world = saas_world
    checks_incompletos = {**reporte["verify_report"], "checks": []}
    for invalid in (
        {"verify_report": None},
        {"verify_report": checks_incompletos},
        {"verify_report": {**reporte["verify_report"], "alembic_revision": "otra_revision"}},
        {"finished_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
    ):
        response = world.client.post(f"{BASE}/backups", headers=SERVICE_HEADERS, json={**reporte, **invalid})
        assert response.status_code == 422, response.text
    assert OpsService(world.db).ultimo_verificado() is None


def test_intento_sin_archivo_es_idempotente_y_no_verificado(saas_world, reporte):
    fallo = {
        **reporte,
        "size_bytes": 0, "sha256": None, "storage_ref": None, "alembic_revision": None,
        "pg_server_version": None, "verify_status": "failed", "verify_report": None,
    }
    respuestas = [saas_world.client.post(f"{BASE}/backups", headers=SERVICE_HEADERS, json=fallo) for _ in range(2)]
    assert all(response.status_code == 200 for response in respuestas)
    assert respuestas[0].json()["data"]["id"] == respuestas[1].json()["data"]["id"]
    assert OpsService(saas_world.db).ultimo_verificado() is None


def test_reverificar_conserva_la_fecha_original_de_la_copia(saas_world, reporte):
    service = OpsService(saas_world.db)
    now = datetime.now(timezone.utc)
    pendiente = {**reporte, "started_at": (now - timedelta(hours=28)).isoformat(),
                 "finished_at": (now - timedelta(hours=27)).isoformat(), "verify_status": "pending", "verify_report": None}
    original = saas_world.client.post(f"{BASE}/backups", headers=SERVICE_HEADERS, json=pendiente)
    retry = saas_world.client.post(f"{BASE}/backups", headers=SERVICE_HEADERS, json=reporte)
    assert original.status_code == retry.status_code == 200
    assert original.json()["data"]["finished_at"] == retry.json()["data"]["finished_at"]
    assert service.ultimo_verificado().verify_status == "ok"


def test_despacho_sin_configuracion_y_evento_cuando_github_acepta(saas_world, monkeypatch):
    world = saas_world
    _permitir(world, "platform.ops.write")
    headers = world.headers(world.platform)
    monkeypatch.setattr(settings, "github_repo", None)
    monkeypatch.setattr(settings, "github_dispatch_token", None)
    body = {"reason": "Verificación manual"}
    missing = world.client.post(f"{BASE}/backups/dispatch", headers=headers, json=body)
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "dispatch_not_configured"

    monkeypatch.setattr(settings, "github_repo", "example/marketplace")
    monkeypatch.setattr(settings, "github_dispatch_token", SecretStr("token-ficticio"))

    def github_post(url, *, json, **kwargs):
        assert url == "https://api.github.com/repos/example/marketplace/actions/workflows/respaldo-bd.yml/dispatches"
        assert json == {"ref": "main", "inputs": {"tipo": "manual"}}
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", github_post)
    accepted = world.client.post(f"{BASE}/backups/dispatch", headers=headers, json=body)
    assert accepted.status_code == 200, accepted.text
    event = world.db.scalar(select(AuditEventModel).where(AuditEventModel.action == "platform.backup_requested"))
    assert event.actor_user_id == world.platform.id
    assert event.metadata_["reason"] == body["reason"]
