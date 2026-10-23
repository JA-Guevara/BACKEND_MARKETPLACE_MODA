from uuid import uuid4
from sqlalchemy import select
from src.auth.infrastructure.persistence.models.user import UserModel
from src.inventario_sucursales.infrastructure.models.organization import CashPointModel


def test_sucursales_cajas_productos_y_usuarios_no_cruzan_empresa(world):
    headers = world.headers(world.admins[0])
    cases = [("organization/branches", world.branches[1].id), ("catalog/admin/products", world.products[1].id), ("users", world.admins[1].id)]
    for path, foreign_id in cases:
        response = world.client.get(f"/api/v1/{path}/{foreign_id}", headers=headers)
        assert response.status_code == 404, response.text
        listed = world.client.get(f"/api/v1/{path}", headers=headers)
        assert listed.status_code == 200, listed.text
        data = listed.json()["data"]
        rows = data["items"] if isinstance(data, dict) else data
        assert str(foreign_id) not in {row["id"] for row in rows}
    cash = CashPointModel(tenant_id=world.tenants[1].id, branch_id=world.branches[1].id, code="BOX", name="Caja B")
    world.db.add(cash); world.db.commit()
    assert world.client.get(f"/api/v1/organization/cash-points/{cash.id}", headers=headers).status_code == 404
    assert world.client.post("/api/v1/organization/cash-points", headers=headers, json={"branch_id": str(world.branches[1].id), "code": "X", "name": "Caja ajena"}).status_code == 404


def test_catalogo_publico_y_sucursales_siguen_empresa_cabecera_y_sesion(world):
    for index in (0, 1):
        headers = {"X-Tenant-Slug": world.tenants[index].slug}
        response = world.client.get("/api/v1/catalog/products", headers=headers)
        assert response.status_code == 200
        assert [row["id"] for row in response.json()["data"]["items"]] == [str(world.products[index].id)]
        detail = world.client.get("/api/v1/catalog/products/prenda-demo", headers=headers)
        assert detail.json()["data"]["id"] == str(world.products[index].id)
        for path in ("public/branches", "commerce/branches"):
            response = world.client.get("/api/v1/"+path, headers=headers)
            assert [row["id"] for row in response.json()["data"]] == [str(world.branches[index].id)]
    assert world.client.get("/api/v1/catalog/products", headers={"X-Tenant-Slug": "inexistente"}).json()["error"]["code"] == "tenant_not_found"
    response = world.client.get("/api/v1/catalog/products", headers={**world.headers(world.admins[0]), "X-Tenant-Slug": "moda-b"})
    assert response.json()["data"]["items"][0]["id"] == str(world.products[0].id)


def test_registro_asigna_empresa_publica_y_prohibe_rol_plataforma(world, monkeypatch):
    from src.auth.application.services.auth_email_service import AuthEmailService
    monkeypatch.setattr(AuthEmailService, "send_verification", lambda *args: False)
    response = world.client.post("/api/v1/auth/register", headers={"X-Tenant-Slug": "moda-b"}, json={"email": "nuevo@example.com", "password": "Segura_12345!Otra", "first_name": "Nuevo", "last_name": "Cliente"})
    assert response.status_code == 201, response.text
    assert world.db.scalar(select(UserModel).where(UserModel.email == "nuevo@example.com")).tenant_id == world.tenants[1].id
    response = world.client.put(f"/api/v1/users/{world.customers[0].id}/roles", headers=world.headers(world.admins[0]), json={"role_ids": [str(world.platform.roles[0].id)]})
    assert response.status_code == 403


def test_suscripcion_no_activa_solo_consulta_y_cupo_sucursal(world):
    headers = world.headers(world.admins[0])
    branch_body = {"code": "EXTRA", "name": "Sucursal Extra", "city_id": str(world.branches[0].city_id), "address": "Av. Test"}
    response = world.client.post("/api/v1/organization/branches", headers=headers, json=branch_body)
    assert response.status_code == 201, response.text
    branch_body["code"], branch_body["name"] = "OTRA", "Sucursal Otra"
    response = world.client.post("/api/v1/organization/branches", headers=headers, json=branch_body)
    assert response.status_code == 409 and response.json()["error"]["code"] == "plan_limit_exceeded"
    from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
    sub = world.db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id == world.tenants[0].id))
    sub.status = "SUSPENDIDA"; world.db.commit()
    assert world.client.get("/api/v1/catalog/admin/products", headers=headers).status_code == 200
    response = world.client.patch(f"/api/v1/catalog/admin/products/{world.products[0].id}", headers=headers, json={"name": "Otro nombre"})
    assert response.status_code == 403 and response.json()["error"]["code"] == "subscription_inactive"


def test_platform_admin_no_entra_en_negocio(world):
    response = world.client.get("/api/v1/tenant/subscription", headers=world.headers(world.platform))
    assert response.status_code == 403 and response.json()["error"]["code"] == "tenant_required"


def test_empresa_no_se_convierte_en_plataforma_por_permisos(world):
    # Incluso si un rol global arrastra permisos SaaS, el alcance de la cuenta
    # sigue siendo su empresa: no se puede administrar otros tenants.
    world.admin_role.permissions.extend(world.platform.roles[0].permissions)
    world.db.commit()
    headers = world.headers(world.admins[0])
    for path in ('platform/tenants', 'platform/plans', f'platform/tenants/{world.tenants[1].id}/subscription'):
        assert world.client.get('/api/v1/'+path, headers=headers).status_code == 403
