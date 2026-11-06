from tests.unit.plataforma_saas.conftest import TEST_PASSWORD


def test_login_en_empresa_valida_pertenencia_y_el_catalogo_es_independiente(world):
    a, b = world.tenants
    a.is_published = b.is_published = True
    world.db.commit()
    url = "/api/v1/auth/login"
    identity = {"email": world.admins[0].email, "password": TEST_PASSWORD}

    denied = world.client.post(url, json={**identity, "tenant_slug": b.slug})
    assert denied.status_code == 401
    allowed = world.client.post(url, json={**identity, "tenant_slug": a.slug})
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["data"]["user"]["tenant"]["slug"] == a.slug
    assert world.client.post(url, json={**identity, "platform_login": True}).status_code == 401
    assert world.client.post(url, json={
        "email": world.platform.email, "password": TEST_PASSWORD, "platform_login": True,
    }).status_code == 200

    for index, tenant in enumerate((a, b)):
        result = world.client.get("/api/v1/catalog/products", headers={"X-Tenant-Slug": tenant.slug})
        assert result.status_code == 200, result.text
        assert [row["id"] for row in result.json()["data"]["items"]] == [str(world.products[index].id)]


def test_primera_instantanea_toma_la_empresa_del_token_sin_elegir_sucursal(world):
    headers = world.headers(world.admins[0])
    response = world.client.get("/api/v1/offline/snapshot", headers={
        **headers, "X-Tenant-Slug": world.tenants[1].slug,
    })
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["tenant"]["slug"] == world.tenants[0].slug
    assert [row["id"] for row in data["products"]] == [str(world.products[0].id)]
    assert [row["id"] for row in data["branches"]] == [str(world.branches[0].id)]
