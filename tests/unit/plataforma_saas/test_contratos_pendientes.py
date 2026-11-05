from src.roles.infrastructure.persistence.models.role import RoleModel


def test_get_limits_de_empresa_solo_para_plataforma(saas_world):
    world = saas_world
    tenant = world.tenants[0]
    path = f"/api/v1/platform/tenants/{tenant.id}/limits"

    assert world.client.get(path, headers=world.headers(world.admins[0])).status_code == 403

    respuesta = world.client.get(path, headers=world.headers(world.platform))
    assert respuesta.status_code == 200, respuesta.text
    limites = {item["limit_code"]: item for item in respuesta.json()["data"]}
    assert limites["max_active_branches"]["plan_value"] == 2
    assert limites["max_active_branches"]["effective_value"] == 2
    assert limites["max_active_branches"]["source"] == "PLAN"


def test_put_permisos_de_rol_de_empresa_respeta_alcance_y_aislamiento(saas_world):
    world = saas_world
    tenant_a, tenant_b = world.tenants
    role_a = RoleModel(
        tenant_id=tenant_a.id,
        code="supervisor_a",
        name="Supervisor A",
        audience="TENANT",
        is_system=False,
    )
    role_b = RoleModel(
        tenant_id=tenant_b.id,
        code="supervisor_b",
        name="Supervisor B",
        audience="TENANT",
        is_system=False,
    )
    world.db.add_all([role_a, role_b])
    world.db.commit()

    url_a = f"/api/v1/platform/tenants/{tenant_a.id}/roles/{role_a.id}/permissions"
    respuesta = world.client.put(
        url_a,
        headers=world.headers(world.platform),
        json={"permission_codes": ["catalog.read", "users.read"], "reason": "Habilitar supervisión"},
    )
    assert respuesta.status_code == 200, respuesta.text
    codigos = {permiso["code"] for permiso in respuesta.json()["data"]["permissions"]}
    assert codigos == {"catalog.read", "users.read"}

    # Un rol de la empresa B no existe en el path de la empresa A.
    url_b_en_a = f"/api/v1/platform/tenants/{tenant_a.id}/roles/{role_b.id}/permissions"
    assert world.client.put(
        url_b_en_a,
        headers=world.headers(world.platform),
        json={"permission_codes": ["catalog.read"], "reason": "Intento cruzado"},
    ).status_code == 404

    # El administrador de la empresa no puede entrar por la consola de plataforma.
    assert world.client.put(
        url_a,
        headers=world.headers(world.admins[0]),
        json={"permission_codes": ["catalog.read"], "reason": "Sin alcance"},
    ).status_code == 403


def test_sucursales_autorizadas_del_usuario_y_en_auth_me(saas_world):
    world = saas_world
    admin_a = world.admins[0]
    cliente_a = world.customers[0]
    branch_a, branch_b = world.branches
    url = f"/api/v1/users/{cliente_a.id}/branches"

    inicial = world.client.get(url, headers=world.headers(admin_a))
    assert inicial.status_code == 200, inicial.text
    assert inicial.json()["data"] == []

    asignacion = world.client.put(
        url,
        headers=world.headers(admin_a),
        json={
            "branch_ids": [str(branch_a.id)],
            "default_branch_id": str(branch_a.id),
        },
    )
    assert asignacion.status_code == 200, asignacion.text
    assert asignacion.json()["data"][0]["is_default"] is True

    me = world.client.get("/api/v1/auth/me", headers=world.headers(cliente_a))
    assert me.status_code == 200, me.text
    autorizadas = me.json()["data"]["authorized_branches"]
    assert [(item["id"], item["code"], item["is_default"]) for item in autorizadas] == [
        (str(branch_a.id), branch_a.code, True)
    ]

    # Una sucursal de la empresa B no se puede asignar desde la empresa A.
    cruzada = world.client.put(
        url,
        headers=world.headers(admin_a),
        json={"branch_ids": [str(branch_b.id)]},
    )
    assert cruzada.status_code == 404
