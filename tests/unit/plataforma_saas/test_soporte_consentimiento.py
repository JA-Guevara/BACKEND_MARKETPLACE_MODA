import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.plataforma_saas.infrastructure.models.support_session import SupportSessionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.roles.infrastructure.persistence.models.permission import PermissionModel


@pytest.fixture(autouse=True)
def setup_support_permissions(world):
    p_approve = world.db.execute(
        select(PermissionModel).where(PermissionModel.code == "support_access.approve")
    ).scalar_one_or_none()
    if not p_approve:
        p_approve = PermissionModel(
            code="support_access.approve",
            name="Aprobar accesos de soporte",
            module="support",
            scope="tenant",
        )
        world.db.add(p_approve)
        world.db.flush()

    if p_approve not in world.admin_role.permissions:
        world.admin_role.permissions.append(p_approve)

    p_emerg = world.db.execute(
        select(PermissionModel).where(PermissionModel.code == "support.emergency")
    ).scalar_one_or_none()
    if not p_emerg:
        p_emerg = PermissionModel(
            code="support.emergency",
            name="Acceso de emergencia",
            module="support",
            scope="platform",
        )
        world.db.add(p_emerg)
        world.db.flush()

    if p_emerg not in world.platform_role.permissions:
        world.platform_role.permissions.append(p_emerg)

    world.db.commit()


def test_pendiente_no_emite_token(world):
    """Regla PX0.2: Una solicitud pendiente nunca emite token de acceso."""
    tenant_a = world.tenants[0]
    # Política por defecto: require_approval
    t = world.db.get(TenantModel, tenant_a.id)
    t.support_access_mode = "require_approval"
    world.db.commit()

    resp = world.client.post(
        "/api/v1/platform/support/sessions",
        headers=world.headers(world.platform),
        json={
            "tenant_id": str(tenant_a.id),
            "reason": "Revisión de problemas con inventario y facturación",
            "duration_minutes": 60,
            "mode": "WRITE",
        },
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()["data"]
    assert body["session"]["status"] == "pending_approval"
    assert body["session"]["is_active"] is False
    assert body["access_token"] is None
    assert body["expires_in"] == 0
    assert body["permissions"] == []
    assert body["session"]["request_expires_at"] is not None


def test_solo_la_empresa_duena_aprueba(world):
    """Regla PX0.2 / RN03: Solo el administrador de la empresa dueña puede aprobar."""
    tenant_a = world.tenants[0]
    resp_req = world.client.post(
        "/api/v1/platform/support/sessions",
        headers=world.headers(world.platform),
        json={
            "tenant_id": str(tenant_a.id),
            "reason": "Solicitud para verificación de inventario",
            "duration_minutes": 60,
            "mode": "WRITE",
        },
    )
    assert resp_req.status_code == 202
    session_id = resp_req.json()["data"]["session"]["id"]

    # Admin de empresa B intenta aprobar -> debe fallar con 403
    resp_b = world.client.post(
        f"/api/v1/tenant/support/requests/{session_id}/approve",
        headers=world.headers(world.admins[1]),
        json={"minutes": 30},
    )
    assert resp_b.status_code == 403, "Empresa ajena no debe poder aprobar"

    # Admin de empresa A (dueña) aprueba
    resp_a = world.client.post(
        f"/api/v1/tenant/support/requests/{session_id}/approve",
        headers=world.headers(world.admins[0]),
        json={"minutes": 30},
    )
    assert resp_a.status_code == 200, resp_a.text
    approved_data = resp_a.json()["data"]
    assert approved_data["status"] == "approved"
    assert approved_data["duration_minutes"] == 30
    assert approved_data["approved_by_user_id"] == str(world.admins[0].id)
    assert approved_data["is_active"] is True

    # Verificar evento auditado en bitácora
    audit = world.db.execute(
        select(AuditEventModel).where(
            AuditEventModel.entity_id == session_id,
            AuditEventModel.action == "support.approved",
        )
    ).scalar_one_or_none()
    assert audit is not None
    assert audit.tenant_id == tenant_a.id


def test_rechazo_con_motivo_y_auditoria(world):
    """Regla PX0.2: La empresa puede rechazar con motivo explícito."""
    tenant_a = world.tenants[0]
    resp_req = world.client.post(
        "/api/v1/platform/support/sessions",
        headers=world.headers(world.platform),
        json={
            "tenant_id": str(tenant_a.id),
            "reason": "Petición que será rechazada por política interna",
            "duration_minutes": 60,
            "mode": "WRITE",
        },
    )
    session_id = resp_req.json()["data"]["session"]["id"]

    resp_rej = world.client.post(
        f"/api/v1/tenant/support/requests/{session_id}/reject",
        headers=world.headers(world.admins[0]),
        json={"reason": "No autorizamos acceso en horario comercial"},
    )
    assert resp_rej.status_code == 200
    data = resp_rej.json()["data"]
    assert data["status"] == "rejected"
    assert data["decision_reason"] == "No autorizamos acceso en horario comercial"
    assert data["is_active"] is False

    # Intento de entrar a la sesión rechazada falla
    resp_enter = world.client.post(
        f"/api/v1/platform/support/sessions/{session_id}/enter",
        headers=world.headers(world.platform),
    )
    assert resp_enter.status_code == 403


def test_solicitud_vence_a_los_10_min(world):
    """Regla PX0.2: Si nadie responde en 10 minutos, la solicitud expira (410)."""
    tenant_a = world.tenants[0]
    resp_req = world.client.post(
        "/api/v1/platform/support/sessions",
        headers=world.headers(world.platform),
        json={
            "tenant_id": str(tenant_a.id),
            "reason": "Sesión que va a vencer por tiempo de espera",
            "duration_minutes": 60,
            "mode": "WRITE",
        },
    )
    session_id = uuid.UUID(resp_req.json()["data"]["session"]["id"])

    # Forzar fecha de expiración en el pasado
    sess = world.db.get(SupportSessionModel, session_id)
    sess.request_expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    world.db.commit()

    # Intentar aprobar solicitud vencida
    resp_app = world.client.post(
        f"/api/v1/tenant/support/requests/{session_id}/approve",
        headers=world.headers(world.admins[0]),
        json={"minutes": 30},
    )
    assert resp_app.status_code == 410, resp_app.text
    assert resp_app.json()["error"]["code"] == "support_request_expired"


def test_emergencia_exige_permiso_y_motivo(world):
    """Regla PX0.2: Acceso de emergencia exige support.emergency, motivo >= 20 chars y dura <= 30 min."""
    tenant_a = world.tenants[0]

    # Usuario sin permiso support.emergency (admin de empresa)
    resp_noperm = world.client.post(
        "/api/v1/platform/support/sessions/emergency",
        headers=world.headers(world.admins[0]),
        json={
            "tenant_id": str(tenant_a.id),
            "reason": "Incidente crítico en base de datos de producción",
            "duration_minutes": 30,
        },
    )
    assert resp_noperm.status_code == 403

    # Motivo demasiado corto (< 20 caracteres)
    resp_short = world.client.post(
        "/api/v1/platform/support/sessions/emergency",
        headers=world.headers(world.platform),
        json={
            "tenant_id": str(tenant_a.id),
            "reason": "Motivo muy corto",
            "duration_minutes": 30,
        },
    )
    assert resp_short.status_code == 422

    # Caso exitoso: motivo >= 20 caracteres con superadmin
    resp_ok = world.client.post(
        "/api/v1/platform/support/sessions/emergency",
        headers=world.headers(world.platform),
        json={
            "tenant_id": str(tenant_a.id),
            "reason": "Caída del servicio de pagos en pasarela externa de la empresa",
            "duration_minutes": 30,
        },
    )
    assert resp_ok.status_code == 201, resp_ok.text
    data = resp_ok.json()["data"]
    assert data["session"]["is_emergency"] is True
    assert data["session"]["status"] == "active"
    assert data["access_token"] is not None
    assert len(data["permissions"]) > 0

    # Evento de auditoría de emergencia
    audit = world.db.execute(
        select(AuditEventModel).where(
            AuditEventModel.entity_id == data["session"]["id"],
            AuditEventModel.action == "support.emergency",
        )
    ).scalar_one_or_none()
    assert audit is not None


def test_allow_read_only_no_exime_asistencia_escritura(world):
    """Regla PX0.2: allow_read_only solo exime al alcance de solo lectura."""
    tenant_a = world.tenants[0]
    t = world.db.get(TenantModel, tenant_a.id)
    t.support_access_mode = "allow_read_only"
    world.db.commit()

    # Intento de acceso de escritura (WRITE) requiere aprobación
    resp_write = world.client.post(
        "/api/v1/platform/support/sessions",
        headers=world.headers(world.platform),
        json={
            "tenant_id": str(tenant_a.id),
            "reason": "Acceso para modificar registros de inventario",
            "duration_minutes": 60,
            "mode": "WRITE",
        },
    )
    assert resp_write.status_code == 202
    assert resp_write.json()["data"]["session"]["status"] == "pending_approval"
    assert resp_write.json()["data"]["access_token"] is None

    # Acceso de solo lectura (READ_ONLY) se aprueba de inmediato
    resp_ro = world.client.post(
        "/api/v1/platform/support/sessions",
        headers=world.headers(world.platform),
        json={
            "tenant_id": str(tenant_a.id),
            "reason": "Inspección de reportes y consultas de solo lectura",
            "duration_minutes": 60,
            "mode": "READ_ONLY",
        },
    )
    assert resp_ro.status_code == 201
    assert resp_ro.json()["data"]["session"]["status"] == "active"
    assert resp_ro.json()["data"]["access_token"] is not None


def test_entrar_tras_aprobacion_emite_token(world):
    """Flujo completo: Petición -> Aprobación de empresa -> Soporte entra con token RFC 8693."""
    tenant_a = world.tenants[0]
    t = world.db.get(TenantModel, tenant_a.id)
    t.support_access_mode = "require_approval"
    world.db.commit()

    # 1. Plataforma pide soporte
    resp1 = world.client.post(
        "/api/v1/platform/support/sessions",
        headers=world.headers(world.platform),
        json={
            "tenant_id": str(tenant_a.id),
            "reason": "Asistencia técnica para configuración de sucursal",
            "duration_minutes": 60,
            "mode": "WRITE",
        },
    )
    assert resp1.status_code == 202
    session_id = resp1.json()["data"]["session"]["id"]

    # 2. Soporte no puede entrar antes de la aprobación
    resp_early = world.client.post(
        f"/api/v1/platform/support/sessions/{session_id}/enter",
        headers=world.headers(world.platform),
    )
    assert resp_early.status_code == 409

    # 3. Empresa aprueba
    resp_app = world.client.post(
        f"/api/v1/tenant/support/requests/{session_id}/approve",
        headers=world.headers(world.admins[0]),
        json={"minutes": 60},
    )
    assert resp_app.status_code == 200

    # 4. Soporte entra exitosamente y obtiene token
    resp_enter = world.client.post(
        f"/api/v1/platform/support/sessions/{session_id}/enter",
        headers=world.headers(world.platform),
    )
    assert resp_enter.status_code == 200
    body = resp_enter.json()["data"]
    assert body["access_token"] is not None
    assert body["session"]["status"] == "approved"
    assert body["session"]["is_active"] is True
    assert "catalog.write" in body["permissions"]


def test_politica_soporte_actualizar_y_consultar(world):
    """La empresa puede consultar y cambiar su política de soporte."""
    # Consultar política inicial
    resp_get = world.client.get(
        "/api/v1/tenant/support/policy",
        headers=world.headers(world.admins[0]),
    )
    assert resp_get.status_code == 200
    assert resp_get.json()["data"]["support_access_mode"] in ("require_approval", "allow_read_only")

    # Cambiar política a allow_read_only
    resp_put = world.client.put(
        "/api/v1/tenant/support/policy",
        headers=world.headers(world.admins[0]),
        json={"mode": "allow_read_only"},
    )
    assert resp_put.status_code == 200
    assert resp_put.json()["data"]["support_access_mode"] == "allow_read_only"
