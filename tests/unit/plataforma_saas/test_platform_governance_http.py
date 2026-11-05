from uuid import uuid4
import pytest
from sqlalchemy import select

from src.roles.infrastructure.persistence.models.role import RoleModel
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from tests.unit.plataforma_saas.conftest import make_token


def test_post_user_tenant_with_wrong_tenant_role_returns_422(client, world):
    token = make_token(world.platform_user)

    # Rol propio de Empresa A
    role_a = RoleModel(
        code="custom_role_a",
        name="Rol Propio A",
        tenant_id=world.tenant_a.id,
        audience="TENANT",
    )
    world.db.add(role_a)
    world.db.commit()

    # Intentar crear usuario en Empresa B con rol de Empresa A
    payload = {
        "kind": "tenant",
        "tenant_id": str(world.tenant_b.id),
        "first_name": "Invalido",
        "last_name": "Usuario",
        "email": "invalido@example.com",
        "role_ids": [str(role_a.id)],
        "access": "invite",
    }
    resp = client.post("/api/v1/platform/users", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422
    assert "role_tenant_mismatch" in resp.text


def test_post_user_tenant_with_template_cashier_success_and_temp_pass(client, world):
    token = make_token(world.platform_user)

    cashier_role = world.db.scalar(select(RoleModel).where(RoleModel.code == "cashier"))
    assert cashier_role is not None

    payload = {
        "kind": "tenant",
        "tenant_id": str(world.tenant_a.id),
        "first_name": "Cajero",
        "last_name": "Nuevo",
        "email": "cajero.nuevo@example.com",
        "phone": "+591 71234567",
        "role_ids": [str(cashier_role.id)],
        "access": "temporary_password",
    }
    resp = client.post("/api/v1/platform/users", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["email"] == "cajero.nuevo@example.com"
    assert data["must_change_password"] is True
    assert data["temporary_password"] is not None
    assert data["temporary_password"].startswith("Tmp_")


def test_removing_last_active_admin_returns_409(client, world):
    token = make_token(world.platform_user)
    cashier_role = world.db.scalar(select(RoleModel).where(RoleModel.code == "cashier"))

    # Intentar quitarle el rol admin al único admin de Tenant A asignándole solo cashier
    resp = client.put(
        f"/api/v1/platform/users/{world.admin_a.id}/roles",
        json={"role_ids": [str(cashier_role.id)]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert "last_tenant_admin" in resp.text


def test_get_effective_permissions_explains_role_and_module(client, world):
    token = make_token(world.platform_user)

    resp = client.get(
        f"/api/v1/platform/users/{world.admin_a.id}/effective-permissions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    perms = resp.json()["data"]["permissions"]
    assert len(perms) > 0
    # Permiso que tiene el admin
    catalog_read = next((p for p in perms if p["code"] == "catalog.read"), None)
    assert catalog_read is not None
    assert catalog_read["status"] in ("PERMITIDO", "PRUEBA")
    assert catalog_read["granted_by_role"] == "Administrador"


def test_update_template_without_confirm_returns_409_with_confirm_200(client, world):
    token = make_token(world.platform_user)
    cashier_role = world.db.scalar(select(RoleModel).where(RoleModel.code == "cashier"))

    # Sin confirmación
    payload = {
        "permission_codes": ["catalog.read"],
        "reason": "Reducir permisos de cajero",
        "confirm": False,
    }
    resp = client.put(
        f"/api/v1/platform/roles/templates/{cashier_role.id}/permissions",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert "impact" in body.get("error", {}).get("code", "") or "impact" in str(body)

    # Con confirmación
    payload["confirm"] = True
    resp_ok = client.put(
        f"/api/v1/platform/roles/templates/{cashier_role.id}/permissions",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["data"]["permissions"] == ["catalog.read"]


def test_platform_role_with_tenant_scope_permission_returns_422(client, world):
    token = make_token(world.platform_user)

    # catalog.read es scope tenant
    payload = {
        "code": "new_team_role",
        "name": "Nuevo Rol Equipo",
        "description": "Prueba",
        "permission_codes": ["catalog.read"],
    }
    resp = client.post("/api/v1/platform/roles/team", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422
    assert "scope" in resp.text.lower()


def test_patch_permission_does_not_change_code(client, world):
    token = make_token(world.platform_user)
    perm = world.db.scalar(select(PermissionModel).where(PermissionModel.code == "catalog.read"))

    resp = client.patch(
        f"/api/v1/platform/permissions/{perm.id}",
        json={"name": "Lectura de Catálogo Modificada", "description": "Nueva descripción"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["code"] == "catalog.read"
    assert data["name"] == "Lectura de Catálogo Modificada"


def test_sandbox_reset_on_non_sandbox_tenant_returns_409(client, world):
    token = make_token(world.platform_user)

    # world.tenant_a tiene is_sandbox = False
    from src.plataforma_saas.application.sandbox_service import SandboxService
    svc = SandboxService(world.db)
    with pytest.raises(Exception) as exc_info:
        svc.reset(world.platform_user, world.tenant_a.id, confirm=True)
    assert exc_info.value.code == "sandbox_only" or "sandbox" in str(exc_info.value).lower() or "demo" in str(exc_info.value).lower()
