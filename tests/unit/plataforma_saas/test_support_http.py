import uuid
from sqlalchemy import select
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.plataforma_saas.infrastructure.models.support_session import SupportSessionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.usuarios_catalogo.infrastructure.models.catalog import ProductModel


def test_post_support_session_valida_201_expires_in_y_permissions(world):
    tenant_a = world.tenants[0]
    payload = {
        "reason": "Revisión de problemas con inventario y facturación",
        "duration_minutes": 60,
    }
    resp = world.client.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/support-sessions",
        headers=world.headers(world.platform),
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert "access_token" in data
    assert 3550 <= data["expires_in"] <= 3600
    perms = data["permissions"]
    assert "catalog.write" in perms
    assert "tenants.read" not in perms
    assert data["session"]["tenant_id"] == str(tenant_a.id)
    assert data["session"]["is_active"] is True


def test_post_support_session_motivo_corto_422(world):
    tenant_a = world.tenants[0]
    payload = {
        "reason": "Corto",
        "duration_minutes": 60,
    }
    resp = world.client.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/support-sessions",
        headers=world.headers(world.platform),
        json=payload,
    )
    assert resp.status_code == 422


def test_post_support_session_empresa_inactiva_403_tenant_inactive(world):
    tenant_a = world.tenants[0]
    # Poner la empresa inactiva
    t = world.db.get(TenantModel, tenant_a.id)
    t.status = "INACTIVA"
    world.db.commit()

    payload = {
        "reason": "Intento de soporte en empresa inactiva",
        "duration_minutes": 60,
    }
    resp = world.client.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/support-sessions",
        headers=world.headers(world.platform),
        json=payload,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "tenant_inactive"

    # Restaurar estado
    t.status = "ACTIVA"
    world.db.commit()


def test_admin_de_empresa_intenta_iniciar_soporte_retorna_403(world):
    tenant_a = world.tenants[0]
    payload = {
        "reason": "Intento no autorizado de soporte",
        "duration_minutes": 60,
    }
    resp = world.client.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/support-sessions",
        headers=world.headers(world.admins[0]),
        json=payload,
    )
    assert resp.status_code == 403


def test_con_token_soporte_consulta_y_crea_producto_y_audita_con_support_session_id(world):
    tenant_a = world.tenants[0]
    # Iniciar sesión de soporte
    resp = world.client.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/support-sessions",
        headers=world.headers(world.platform),
        json={"reason": "Auditoría de catálogo con soporte", "duration_minutes": 60},
    )
    assert resp.status_code == 201
    support_data = resp.json()["data"]
    token = support_data["access_token"]
    session_id = uuid.UUID(support_data["session"]["id"])
    support_headers = {"Authorization": f"Bearer {token}"}

    # GET /catalog/admin/products -> prendas de A
    resp_prod = world.client.get("/api/v1/catalog/admin/products", headers=support_headers)
    assert resp_prod.status_code == 200, resp_prod.text
    prods = resp_prod.json()["data"]["items"]
    assert len(prods) >= 1
    for p in prods:
        assert p["name"] != "Prenda 1"  # Prenda 1 es de B

    # POST crea con tenant_id A y bitácora con support_session_id
    cat_a = world.category
    create_body = {
        "name": "Vestido Soporte",
        "description": "Creado durante sesión de soporte",
        "base_price": 250,
        "category_id": str(cat_a.id),
        "variants": [
            {
                "size_id": str(world.size.id),
                "color_id": str(world.color.id),
                "sku": "SOPORTE-01",
            }
        ],
        "images": [],
        "suppliers": [],
    }
    resp_create = world.client.post(
        "/api/v1/catalog/admin/products",
        headers=support_headers,
        json=create_body,
    )
    assert resp_create.status_code == 201, resp_create.text
    created_id = uuid.UUID(resp_create.json()["data"]["id"])

    # Verificar producto en base de datos
    db_product = world.db.get(ProductModel, created_id)
    assert db_product is not None
    assert db_product.tenant_id == tenant_a.id

    # Verificar evento de auditoría
    audit = world.db.scalar(
        select(AuditEventModel).where(
            AuditEventModel.action == "catalog.product_created",
            AuditEventModel.entity_id == str(created_id),
        )
    )
    assert audit is not None
    assert audit.tenant_id == tenant_a.id
    assert audit.support_session_id == session_id


def test_con_token_soporte_get_platform_tenants_retorna_403_platform_scope_only(world):
    tenant_a = world.tenants[0]
    resp = world.client.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/support-sessions",
        headers=world.headers(world.platform),
        json={"reason": "Prueba de aislamiento de plataforma", "duration_minutes": 60},
    )
    token = resp.json()["data"]["access_token"]
    support_headers = {"Authorization": f"Bearer {token}"}

    resp_platform = world.client.get("/api/v1/platform/tenants", headers=support_headers)
    assert resp_platform.status_code == 403
    assert resp_platform.json()["error"]["code"] == "platform_scope_only"


def test_post_end_con_token_soporte_200_y_siguiente_401_support_session_expired(world):
    tenant_a = world.tenants[0]
    resp = world.client.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/support-sessions",
        headers=world.headers(world.platform),
        json={"reason": "Sesión a finalizar inmediatamente", "duration_minutes": 60},
    )
    token = resp.json()["data"]["access_token"]
    session_id = resp.json()["data"]["session"]["id"]
    support_headers = {"Authorization": f"Bearer {token}"}

    # Finalizar con el token de soporte
    resp_end = world.client.post(
        f"/api/v1/platform/support-sessions/{session_id}/end",
        headers=support_headers,
    )
    assert resp_end.status_code == 200, resp_end.text
    assert resp_end.json()["data"]["is_active"] is False

    # Siguiente petición con ese token -> 401 support_session_expired
    resp_after = world.client.get("/api/v1/catalog/admin/products", headers=support_headers)
    assert resp_after.status_code == 401
    assert resp_after.json()["error"]["code"] == "support_session_expired"


def test_extender_hasta_superar_240_min_retorna_409_support_limit_exceeded(world):
    tenant_a = world.tenants[0]
    # Inicia con 120 min
    resp = world.client.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/support-sessions",
        headers=world.headers(world.platform),
        json={"reason": "Sesión para probar extensión de tiempo", "duration_minutes": 120},
    )
    token = resp.json()["data"]["access_token"]
    session_id = resp.json()["data"]["session"]["id"]
    support_headers = {"Authorization": f"Bearer {token}"}

    # Extiende 60 -> total 180
    resp_ext1 = world.client.post(
        f"/api/v1/platform/support-sessions/{session_id}/extend",
        headers=support_headers,
        json={"minutes": 60},
    )
    assert resp_ext1.status_code == 200
    assert resp_ext1.json()["data"]["session"]["duration_minutes"] == 180

    # Extiende 60 -> total 240
    resp_ext2 = world.client.post(
        f"/api/v1/platform/support-sessions/{session_id}/extend",
        headers=support_headers,
        json={"minutes": 60},
    )
    assert resp_ext2.status_code == 200
    assert resp_ext2.json()["data"]["session"]["duration_minutes"] == 240

    # Extiende 15 más -> supera 240 -> 409 support_limit_exceeded
    resp_ext3 = world.client.post(
        f"/api/v1/platform/support-sessions/{session_id}/extend",
        headers=support_headers,
        json={"minutes": 15},
    )
    assert resp_ext3.status_code == 409
    assert resp_ext3.json()["error"]["code"] == "support_limit_exceeded"


def test_iniciar_segunda_sesion_revoca_la_anterior(world):
    tenant_a = world.tenants[0]
    tenant_b = world.tenants[1]

    # Sesión 1
    resp1 = world.client.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/support-sessions",
        headers=world.headers(world.platform),
        json={"reason": "Primera sesión en empresa A", "duration_minutes": 60},
    )
    session1_id = uuid.UUID(resp1.json()["data"]["session"]["id"])

    # Sesión 2
    resp2 = world.client.post(
        f"/api/v1/platform/tenants/{tenant_b.id}/support-sessions",
        headers=world.headers(world.platform),
        json={"reason": "Segunda sesión en empresa B", "duration_minutes": 60},
    )
    assert resp2.status_code == 201

    # Verificar que sesión 1 quedó end_reason == 'revoked'
    s1 = world.db.get(SupportSessionModel, session1_id)
    assert s1.ended_at is not None
    assert s1.end_reason == "revoked"


def test_get_auth_me_con_token_soporte_retorna_tenant_a_y_support_is_active(world):
    tenant_a = world.tenants[0]
    resp = world.client.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/support-sessions",
        headers=world.headers(world.platform),
        json={"reason": "Prueba de /auth/me durante soporte", "duration_minutes": 60},
    )
    token = resp.json()["data"]["access_token"]
    support_headers = {"Authorization": f"Bearer {token}"}

    resp_me = world.client.get("/api/v1/auth/me", headers=support_headers)
    assert resp_me.status_code == 200, resp_me.text
    data = resp_me.json()["data"]

    assert data["tenant"]["id"] == str(tenant_a.id)
    assert data["support"] is not None
    assert data["support"]["is_active"] is True
    assert data["support"]["tenant_id"] == str(tenant_a.id)



def test_soporte_no_puede_previsualizar_catalogo_de_otra_empresa(world):
    a, b = world.tenants
    b.is_published = False
    world.db.commit()
    start = world.client.post(
        f"/api/v1/platform/tenants/{a.id}/support-sessions",
        headers=world.headers(world.platform),
        json={"reason": "Revisar aislamiento de tienda en modo soporte", "duration_minutes": 30},
    )
    token = start.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-Slug": b.slug}
    response = world.client.get("/api/v1/catalog/products", headers=headers)
    assert response.status_code in {403, 404, 409}, response.text
    preview = world.client.get(f"/api/v1/public/stores/{b.slug}", headers=headers)
    assert preview.status_code == 404, preview.text
