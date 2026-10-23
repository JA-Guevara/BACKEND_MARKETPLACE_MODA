from datetime import date, timedelta
from sqlalchemy import func, select
from src.auth.application.services.auth_email_service import AuthEmailService
from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.persistence.models.password_reset_token import PasswordResetTokenModel
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.auth.infrastructure.security.jwt_service import JWTService


def tenant_body(**changes):
    return dict(legal_name="Moda Cruceña SRL", trade_name="Moda Cruceña", tax_id="123456789", slug="moda-crucena",
        contact_email="contacto@example.com", admin={"first_name": "Ana", "last_name": "Lopez", "email": "ana@example.com"}, plan_code="BASICO", **changes)


def test_registrar_empresa_admin_suscripcion_bitacora_y_correo_fallido(world, monkeypatch):
    sent = []
    monkeypatch.setattr(AuthEmailService, "send_tenant_invitation", lambda self, *args: sent.append(args) or False)
    response = world.client.post("/api/v1/platform/tenants", json=tenant_body(), headers=world.headers(world.platform))
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["status"] == "ACTIVA" and data["admin_password_set"] is False
    assert data["plan_code"] == "BASICO" and data["subscription_status"] == "ACTIVA"
    admin = world.db.scalar(select(UserModel).where(UserModel.email == "ana@example.com"))
    assert str(admin.tenant_id) == data["id"] and [role.code for role in admin.roles] == ["admin"]
    sub = world.db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id == admin.tenant_id))
    assert (sub.end_date-sub.start_date).days+1 == 30
    assert world.db.scalar(select(AuditEventModel).where(AuditEventModel.action == "tenants.created")).entity_type == "tenant"
    assert len(sent) == 1
    token = sent[0][1]
    reset = world.db.scalar(select(PasswordResetTokenModel).where(PasswordResetTokenModel.user_id == admin.id))
    assert reset.token_hash == JWTService.hash_token(token) and token not in reset.token_hash
    reset_response = world.client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "Nueva_Clave2026!Segura"})
    assert reset_response.status_code == 200
    activated = world.client.get(f"/api/v1/platform/tenants/{admin.tenant_id}", headers=world.headers(world.platform)).json()["data"]
    assert activated["admin_password_set"] is True


def test_unicidad_y_validacion_sin_datos_parciales(world):
    headers = world.headers(world.platform)
    assert world.client.post("/api/v1/platform/tenants", json=tenant_body(), headers=headers).status_code == 201
    before = world.db.scalar(select(func.count()).select_from(TenantModel))
    duplicate = world.client.post("/api/v1/platform/tenants", json=tenant_body(), headers=headers)
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "tenant_tax_id_taken"
    body = tenant_body(); body["tax_id"] = "11111222"
    duplicate = world.client.post("/api/v1/platform/tenants", json=body, headers=headers)
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "tenant_slug_taken"
    body["slug"] = "Moda Cruceña"
    assert world.client.post("/api/v1/platform/tenants", json=body, headers=headers).status_code == 422
    assert world.db.scalar(select(func.count()).select_from(TenantModel)) == before
    assert world.client.patch(f"/api/v1/platform/tenants/{world.tenants[0].id}", json={"tax_id": "1"}, headers=headers).status_code == 422


def test_desactivar_bloquea_login_refresh_y_sesion_existente(world):
    user = world.admins[0]
    from conftest import TEST_PASSWORD
    login = world.client.post("/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    assert login.status_code == 200, login.text
    existing = world.headers(user)
    response = world.client.post(f"/api/v1/platform/tenants/{user.tenant_id}/deactivate", json={"reason": "Cierre temporal"}, headers=world.headers(world.platform))
    assert response.status_code == 200
    denied = world.client.post("/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "tenant_inactive"
    assert world.client.get("/api/v1/auth/me", headers=existing).status_code == 403
    assert world.client.post("/api/v1/auth/refresh", json={"refresh_token": login.json()["data"]["refresh_token"]}).status_code == 401
    rows = world.client.get("/api/v1/platform/tenants?status=INACTIVA", headers=world.headers(world.platform)).json()["data"]["items"]
    assert len(rows) == 1 and rows[0]["id"] == str(user.tenant_id)


def test_stats_permisos_y_reenvio(world):
    sub = world.db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id == world.tenants[0].id))
    sub.end_date = date.today()+timedelta(days=5)
    world.db.commit()
    response = world.client.get("/api/v1/platform/tenants/stats", headers=world.headers(world.platform))
    assert response.status_code == 200 and response.json()["data"]["expiring_7d"] == 1
    assert world.client.get("/api/v1/platform/tenants", headers=world.headers(world.customers[0])).status_code == 403
    created = world.client.post("/api/v1/platform/tenants", json=tenant_body(), headers=world.headers(world.platform)).json()["data"]
    response = world.client.post(f"/api/v1/platform/tenants/{created['id']}/resend-invitation", headers=world.headers(world.platform))
    assert response.status_code == 200 and "No se pudo" in response.json()["message"]


def test_login_refresh_y_me_incluyen_contexto(world):
    from conftest import TEST_PASSWORD
    response = world.client.post("/api/v1/auth/login", json={"email": world.admins[0].email, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    tokens = response.json()["data"]
    assert tokens["user"]["tenant"]["slug"] == "moda-a"
    assert tokens["user"]["subscription"]["plan_code"] == "BASICO"
    refresh = world.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 200 and refresh.json()["data"]["user"]["tenant"]["slug"] == "moda-a"
    me = world.client.get("/api/v1/auth/me", headers=world.headers(world.platform)).json()["data"]
    assert me["tenant"] is None and me["subscription"] is None
