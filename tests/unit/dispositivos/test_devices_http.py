"""Pruebas HTTP para gestión de dispositivos, registro, bloqueo y auditoría (CU-12)."""
import uuid
import pytest

from tests.unit.plataforma_saas.conftest import world


def test_dispositivos_registro_bloqueo_y_aislamiento(world):
    tenant_a = world.tenants[0]
    admin_a = world.admins[0]
    headers_a = world.headers(admin_a)

    tenant_b = world.tenants[1]
    admin_b = world.admins[1]
    headers_b = world.headers(admin_b)

    dev_id_pwa = "pwa-caja-central-001"
    dev_id_android = "android-pos-movil-002"

    # 1. Petición a snapshot con X-Device-Id registra el dispositivo PWA
    snap_headers = {
        **headers_a,
        "X-Device-Id": dev_id_pwa,
        "X-Client-Platform": "PWA",
        "X-Client-Version": "web-2026.11.08",
    }
    snap_res = world.client.get("/api/v1/offline/snapshot", headers=snap_headers)
    assert snap_res.status_code == 200, snap_res.text

    # 2. Listar dispositivos de empresa A (GET /tenant/devices)
    list_res = world.client.get("/api/v1/tenant/devices", headers=headers_a)
    assert list_res.status_code == 200, list_res.text
    devices = list_res.json()["data"]["items"]
    assert len(devices) >= 1
    pwa_dev = next((d for d in devices if d["device_id"] == dev_id_pwa), None)
    assert pwa_dev is not None
    assert pwa_dev["platform"] == "PWA"
    assert pwa_dev["status"] == "ACTIVO"
    assert pwa_dev["app_version"] == "web-2026.11.08"
    assert pwa_dev["last_snapshot_at"] is not None

    dev_pk = pwa_dev["id"]

    # 3. Renombrar dispositivo (PATCH /tenant/devices/{id})
    patch_res = world.client.patch(
        f"/api/v1/tenant/devices/{dev_pk}",
        headers=headers_a,
        json={"label": "Caja Principal 01"},
    )
    assert patch_res.status_code == 200, patch_res.text
    assert patch_res.json()["data"]["label"] == "Caja Principal 01"

    # 4. Detalle de dispositivo con bitácora de actividad (GET /tenant/devices/{id})
    detail_res = world.client.get(f"/api/v1/tenant/devices/{dev_pk}", headers=headers_a)
    assert detail_res.status_code == 200, detail_res.text
    detail = detail_res.json()["data"]
    assert detail["label"] == "Caja Principal 01"
    assert len(detail["recent_activity"]) >= 1

    # 5. Exportar CSV (GET /tenant/devices/export.csv)
    csv_res = world.client.get("/api/v1/tenant/devices/export.csv", headers=headers_a)
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers["content-type"]
    assert dev_id_pwa in csv_res.text

    # 6. Bloquear dispositivo (POST /tenant/devices/{id}/block)
    block_res = world.client.post(
        f"/api/v1/tenant/devices/{dev_pk}/block",
        headers=headers_a,
        json={"reason": "Terminal extraviado fuera de la sucursal", "revoke_sessions": True},
    )
    assert block_res.status_code == 200, block_res.text
    assert block_res.json()["data"]["status"] == "BLOQUEADO"

    # 7. Intentar snapshot con dispositivo bloqueado -> 403 device_blocked
    snap_blocked = world.client.get("/api/v1/offline/snapshot", headers=snap_headers)
    assert snap_blocked.status_code == 403, snap_blocked.text
    err_json = snap_blocked.json()
    assert err_json.get("error") == "device_blocked" or err_json.get("detail", {}).get("error") == "device_blocked"

    # Verificar que rejected_attempts incrementó
    detail_res2 = world.client.get(f"/api/v1/tenant/devices/{dev_pk}", headers=headers_a)
    assert detail_res2.json()["data"]["rejected_attempts"] >= 1

    # 8. Reactivar/Desbloquear dispositivo (POST /tenant/devices/{id}/unblock)
    unblock_res = world.client.post(
        f"/api/v1/tenant/devices/{dev_pk}/unblock",
        headers=headers_a,
        json={"reason": "Terminal recuperado y verificado por seguridad"},
    )
    assert unblock_res.status_code == 200, unblock_res.text
    assert unblock_res.json()["data"]["status"] == "ACTIVO"

    # Ahora snapshot funciona nuevamente
    snap_ok = world.client.get("/api/v1/offline/snapshot", headers=snap_headers)
    assert snap_ok.status_code == 200

    # 9. Aislamiento multi-tenant: Empresa B no puede ver ni modificar el dispositivo de Empresa A
    b_detail = world.client.get(f"/api/v1/tenant/devices/{dev_pk}", headers=headers_b)
    assert b_detail.status_code == 404

    b_block = world.client.post(
        f"/api/v1/tenant/devices/{dev_pk}/block",
        headers=headers_b,
        json={"reason": "Ataque cruzado"},
    )
    assert b_block.status_code == 404

    b_list = world.client.get("/api/v1/tenant/devices", headers=headers_b)
    assert b_list.status_code == 200
    assert not any(d["id"] == dev_pk for d in b_list.json()["data"]["items"])


def test_bitacora_filtros_entidad(world):
    tenant_a = world.tenants[0]
    admin_a = world.admins[0]
    headers_a = world.headers(admin_a)

    # Consultar bitácora por entity_type "device"
    audit_res = world.client.get(
        "/api/v1/audit-log",
        headers=headers_a,
        params={"entity_type": "device"},
    )
    assert audit_res.status_code == 200, audit_res.text
    events = audit_res.json()["data"]["items"]
    for evt in events:
        assert evt["entity_type"] == "device"
