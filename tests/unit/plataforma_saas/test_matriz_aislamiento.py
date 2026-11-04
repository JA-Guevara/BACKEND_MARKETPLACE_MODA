import pytest
from uuid import uuid4
from src.roles.infrastructure.persistence.models.role import RoleModel

def test_token_plataforma_sin_empresa_rechazado_en_rutas_empresa(world):
    platform_headers = world.headers(world.platform)
    tenant_endpoints = [
        "/api/v1/organization/branches",
        "/api/v1/catalog/admin/products",
        "/api/v1/roles",
        "/api/v1/tenant/dashboard",
        "/api/v1/tenant/profile",
    ]
    for ep in tenant_endpoints:
        r = world.client.get(ep, headers=platform_headers)
        assert r.status_code == 403, f"Endpoint {ep} should fail with 403 for platform token, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("error", {}).get("code") == "tenant_required", f"Expected tenant_required, got {data}"

@pytest.mark.parametrize(
    "entity_name,path_factory",
    [
        ("branch", lambda w: f"/api/v1/organization/branches/{w.branches[1].id}"),
        ("cash_point", lambda w: f"/api/v1/organization/cash-points/{w.cash_points[1].id}"),
        ("product", lambda w: f"/api/v1/catalog/products/{w.products[1].id}"),
    ],
)
def test_consulta_recurso_empresa_b_con_token_a_responde_404(world, entity_name, path_factory):
    headers_a = world.headers(world.admins[0])
    path = path_factory(world)
    r = world.client.get(path, headers=headers_a)
    assert r.status_code == 404, f"GET {path} con token A debe ser 404, got {r.status_code}: {r.text}"

def test_consulta_rol_empresa_b_con_token_a_responde_404(world):
    # Crear un rol específico para la empresa B
    role_b = RoleModel(
        tenant_id=world.tenants[1].id,
        code="vendedora_b",
        name="Vendedora B",
        description="Rol propio de B",
        is_system=False,
    )
    world.db.add(role_b)
    world.db.commit()

    headers_a = world.headers(world.admins[0])
    r = world.client.get(f"/api/v1/roles/{role_b.id}", headers=headers_a)
    assert r.status_code == 404, f"GET /roles/{role_b.id} debe ser 404, got {r.status_code}: {r.text}"

def test_escritura_con_branch_id_ajeno_responde_404(world):
    headers_a = world.headers(world.admins[0])
    # Intentar crear una caja para una sucursal de la empresa B
    payload = {
        "branch_id": str(world.branches[1].id),
        "code": "CP-CROSS",
        "name": "Caja Cruzada",
    }
    r = world.client.post("/api/v1/organization/cash-points", headers=headers_a, json=payload)
    assert r.status_code == 404, f"Creación con branch_id ajeno debe ser 404, got {r.status_code}: {r.text}"

def test_escritura_con_product_id_ajeno_responde_404(world):
    headers_a = world.headers(world.admins[0])
    # Intentar crear una variante para un producto de la empresa B
    payload = {
        "product_id": str(world.products[1].id),
        "size_id": str(world.size.id),
        "color_id": str(world.color.id),
        "sku": "SKU-CROSS-01",
    }
    r = world.client.post("/api/v1/catalog/variants", headers=headers_a, json=payload)
    assert r.status_code == 404, f"Creación con product_id ajeno debe ser 404, got {r.status_code}: {r.text}"
