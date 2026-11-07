import uuid
from sqlalchemy import select
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.roles.infrastructure.persistence.models.role import RoleModel


def test_admin_a_get_roles_ve_3_sistema_y_propios_pero_no_platform_ni_de_b(world):
    # Crear un rol propio en A y un rol propio en B
    resp_a = world.client.post(
        "/api/v1/roles",
        headers=world.headers(world.admins[0]),
        json={"code": "vendedora_a", "name": "Vendedora A", "description": "Rol de empresa A"},
    )
    assert resp_a.status_code == 201, resp_a.text

    resp_b = world.client.post(
        "/api/v1/roles",
        headers=world.headers(world.admins[1]),
        json={"code": "supervisora_b", "name": "Supervisora B", "description": "Rol de empresa B"},
    )
    assert resp_b.status_code == 201, resp_b.text

    # Admin A consulta roles
    resp = world.client.get("/api/v1/roles", headers=world.headers(world.admins[0]))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    codes = [r["code"] for r in data]
    # 3 de sistema con scope tenant
    assert "admin" in codes
    assert "store_manager" in codes
    assert "cashier" in codes
    # Propios de A
    assert "vendedora_a" in codes
    # Nunca platform_admin ni client ni roles de B
    assert "platform_admin" not in codes
    assert "client" not in codes
    assert "supervisora_b" not in codes

    # Cada RoleResponse agrega is_template: bool y users_count: int
    for role in data:
        assert isinstance(role["is_template"], bool)
        assert isinstance(role["users_count"], int)
        if role["code"] in ("admin", "store_manager", "cashier"):
            assert role["is_template"] is True
        if role["code"] == "vendedora_a":
            assert role["is_template"] is False


def test_admin_a_put_permissions_rol_sistema_retorna_409_system_role_locked(world):
    # Buscar id del rol cashier o admin
    resp = world.client.get("/api/v1/roles", headers=world.headers(world.admins[0]))
    assert resp.status_code == 200
    roles = resp.json()["data"]
    cashier_role = next(r for r in roles if r["code"] == "cashier")

    # Intentar modificar permisos del rol de sistema
    resp = world.client.put(
        f"/api/v1/roles/{cashier_role['id']}/permissions",
        headers=world.headers(world.admins[0]),
        json={"permission_ids": []},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "system_role_locked"


def test_admin_a_put_permisos_con_permiso_de_plataforma_retorna_403_permission_out_of_scope(world):
    # Crear un rol propio en A
    resp_create = world.client.post(
        "/api/v1/roles",
        headers=world.headers(world.admins[0]),
        json={"code": "cajera_extra", "name": "Cajera Extra", "description": "Rol personalizado"},
    )
    assert resp_create.status_code == 201
    custom_role = resp_create.json()["data"]

    # Obtener el permiso platform (tenants.read)
    perm_platform = world.db.scalar(select(PermissionModel).where(PermissionModel.code == "tenants.read"))
    assert perm_platform is not None
    assert perm_platform.scope == "platform"

    # Intentar asignar tenants.read al rol propio
    resp = world.client.put(
        f"/api/v1/roles/{custom_role['id']}/permissions",
        headers=world.headers(world.admins[0]),
        json={"permission_ids": [str(perm_platform.id)]},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "permission_out_of_scope"


def test_admin_a_y_admin_b_post_roles_mismo_code_ambos_201(world):
    # Admin A crea «vendedora»
    resp_a = world.client.post(
        "/api/v1/roles",
        headers=world.headers(world.admins[0]),
        json={"code": "vendedora", "name": "Vendedora de A"},
    )
    assert resp_a.status_code == 201, resp_a.text

    # Admin B crea «vendedora» con el mismo code
    resp_b = world.client.post(
        "/api/v1/roles",
        headers=world.headers(world.admins[1]),
        json={"code": "vendedora", "name": "Vendedora de B"},
    )
    assert resp_b.status_code == 201, resp_b.text

    # Admin A intenta crear «vendedora» de nuevo en su empresa -> 409 conflict
    resp_a_dup = world.client.post(
        "/api/v1/roles",
        headers=world.headers(world.admins[0]),
        json={"code": "vendedora", "name": "Vendedora Duplicada"},
    )
    assert resp_a_dup.status_code == 409


def test_admin_a_put_user_roles_con_rol_de_b_retorna_404(world):
    # Admin B crea un rol propio
    resp_b = world.client.post(
        "/api/v1/roles",
        headers=world.headers(world.admins[1]),
        json={"code": "rol_exclusivo_b", "name": "Rol Exclusivo B"},
    )
    assert resp_b.status_code == 201
    rol_b_id = resp_b.json()["data"]["id"]

    # Admin A intenta asignar ese rol de B a un usuario de A
    user_a = world.customers[0]
    resp = world.client.put(
        f"/api/v1/users/{user_a.id}/roles",
        headers=world.headers(world.admins[0]),
        json={"role_ids": [rol_b_id]},
    )
    assert resp.status_code == 404


def test_admin_a_post_roles_permissions_retorna_403_solo_plataforma(world):
    resp = world.client.post(
        "/api/v1/roles/permissions",
        headers=world.headers(world.admins[0]),
        json={
            "code": "custom.manage",
            "name": "Custom Manage",
            "module": "custom",
            "description": "Permiso no autorizado para empresa",
        },
    )
    assert resp.status_code == 403



def test_catalogo_de_permisos_lista_solo_permisos_de_empresa(world):
    response = world.client.get("/api/v1/roles/permissions/all", headers=world.headers(world.admins[0]))
    assert response.status_code == 200, response.text
    permissions = response.json()["data"]
    assert permissions and {permission["scope"] for permission in permissions} == {"tenant"}


def test_admin_a_patch_user_actualiza_roles(world):
    resp_create = world.client.post(
        '/api/v1/roles',
        headers=world.headers(world.admins[0]),
        json={'code': 'jefe_tienda', 'name': 'Jefe de Tienda', 'description': 'Rol de prueba'},
    )
    assert resp_create.status_code == 201
    custom_role_id = resp_create.json()['data']['id']

    user_a = world.customers[0]
    resp_patch = world.client.patch(
        f'/api/v1/users/{user_a.id}',
        headers=world.headers(world.admins[0]),
        json={'role_ids': [custom_role_id]},
    )
    assert resp_patch.status_code == 200, resp_patch.text
    user_data = resp_patch.json()['data']
    user_roles = [r['id'] for r in user_data['roles']]
    assert custom_role_id in user_roles


def test_admin_a_get_roles_no_incluye_roles_de_plataforma_ni_superadmin(world):
    for rcode, rname, raudience in [
        ("platform_support", "Soporte de plataforma", "PLATFORM"),
        ("platform_billing", "Comercial y facturación", "PLATFORM"),
        ("platform_auditor", "Auditor de plataforma", "PLATFORM"),
        ("superadmin", "Propietario de empresa", "TENANT"),
    ]:
        existing = world.db.scalar(select(RoleModel).where(RoleModel.code == rcode))
        if not existing:
            world.db.add(RoleModel(code=rcode, name=rname, audience=raudience, is_system=True, is_active=True))
    world.db.commit()

    resp = world.client.get("/api/v1/roles?include_inactive=true", headers=world.headers(world.admins[0]))
    assert resp.status_code == 200
    codes = [r["code"] for r in resp.json()["data"]]
    for forbidden in ["platform_admin", "platform_support", "platform_billing", "platform_auditor", "superadmin", "client"]:
        assert forbidden not in codes

    support_role = world.db.scalar(select(RoleModel).where(RoleModel.code == "platform_support"))
    user_a = world.customers[0]
    resp_assign = world.client.put(
        f"/api/v1/users/{user_a.id}/roles",
        headers=world.headers(world.admins[0]),
        json={"role_ids": [str(support_role.id)]},
    )
    assert resp_assign.status_code in (403, 404)
