from datetime import date, datetime, timedelta, timezone
import hashlib
import os
import uuid
import pytest
from sqlalchemy import select

from src.roles.infrastructure.persistence.models.role import RoleModel
from src.auth.infrastructure.persistence.models.user import UserModel
from src.inventario_sucursales.infrastructure.models.organization import (
    BranchModel,
    CashPointModel,
    CityModel,
    UserBranchModel,
)
from src.plataforma_saas.application.signup_service import SignupRequest, SignupService
from src.plataforma_saas.infrastructure.models.plan import PlanModel
from src.plataforma_saas.infrastructure.models.signup_legal import (
    LegalAcceptanceModel,
    LegalDocumentModel,
    TenantSignupModel,
)
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel


def _ensure_legal_docs_and_plan(db):
    terms = db.scalar(select(LegalDocumentModel).where(LegalDocumentModel.code == "terms"))
    if not terms:
        terms = LegalDocumentModel(
            code="terms",
            version="1.0.0",
            content_sha256="fake-terms-sha",
            published_at=datetime.now(timezone.utc),
        )
        privacy = LegalDocumentModel(
            code="privacy",
            version="1.0.0",
            content_sha256="fake-privacy-sha",
            published_at=datetime.now(timezone.utc),
        )
        db.add_all([terms, privacy])
        db.flush()

    prof_plan = db.scalar(select(PlanModel).where(PlanModel.code == "PROFESIONAL"))
    if not prof_plan:
        prof_plan = PlanModel(
            code="PROFESIONAL",
            name="Plan Profesional",
            description="Plan completo",
            reference_price=690.0,
            duration_days=30,
            max_users=10,
            max_active_branches=5,
            is_active=True,
        )
        db.add(prof_plan)
        db.flush()

    city = db.scalar(select(CityModel))
    if not city:
        city = CityModel(id=uuid.uuid4(), name="Santa Cruz", code="SCZ")
        db.add(city)
        db.flush()

    db.commit()


def test_slug_reservado_rechazado(world):
    """Caso obligatorio 3: Slug reservado rechazado en consulta y alta."""
    _ensure_legal_docs_and_plan(world.db)
    service = SignupService(world.db)

    # 1. Palabras reservadas
    slug, disp, mot = service.slug_disponible("admin")
    assert disp is False
    assert "reservado" in mot.lower()

    slug, disp, mot = service.slug_disponible("tienda")
    assert disp is False
    assert "reservado" in mot.lower()

    # 2. Slug ya ocupado por una empresa
    existing_tenant = world.tenants[0]
    slug, disp, mot = service.slug_disponible(existing_tenant.slug)
    assert disp is False
    assert "en uso" in mot.lower()

    # 3. Slug disponible
    slug, disp, mot = service.slug_disponible("Boutique Cruceña Nueva")
    assert disp is True
    assert slug == "boutique-crucena-nueva"

    # 4. HTTP GET /slug
    res = world.client.get("/api/v1/public/signup/slug?name=api")
    assert res.status_code == 200
    assert res.json()["data"]["available"] is False

    res_ok = world.client.get("/api/v1/public/signup/slug?name=MiTiendaChic")
    assert res_ok.status_code == 200
    assert res_ok.json()["data"]["available"] is True
    assert res_ok.json()["data"]["slug"] == "mitiendachic"


def test_correo_existente_responde_igual(world):
    """Caso obligatorio 1: Correo existente responde igual (no revela cuentas)."""
    _ensure_legal_docs_and_plan(world.db)
    existing_admin = world.admins[0]

    payload = {
        "company_name": "Nueva Tienda Espía",
        "slug": "nueva-tienda-espia",
        "email": existing_admin.email,
        "password": "Password1234!",
        "accept_terms": True,
        "accept_privacy": True,
    }

    res = world.client.post("/api/v1/public/signup", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert "recibirás instrucciones" in body["message"].lower()

    # Verificar que no se creó registro de signup para este correo existente
    signup = world.db.scalar(
        select(TenantSignupModel).where(TenantSignupModel.email == existing_admin.email.lower())
    )
    assert signup is None


def test_crea_empresa_admin_sucursal_y_prueba_14_dias(world):
    """Caso obligatorio 4: Proceso completo crea empresa, admin, sucursal y prueba de 14 días."""
    _ensure_legal_docs_and_plan(world.db)

    email = "admin@altanueva.bo"
    payload = {
        "company_name": "Alta Autoservicio Moda",
        "slug": "alta-autoservicio-moda",
        "email": email,
        "password": "PasswordSuperSeguro123!",
        "accept_terms": True,
        "accept_privacy": True,
    }

    # 1. Solicitar alta
    res = world.client.post("/api/v1/public/signup", json=payload)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["email"] == email

    # Buscar el signup en base de datos para obtener el token
    signup = world.db.scalar(
        select(TenantSignupModel).where(TenantSignupModel.email == email)
    )
    assert signup is not None
    assert signup.verified_at is None
    assert signup.tenant_id is None

    # Simular verificación con el token devuelto en dev_token o generado
    token = data.get("dev_token")
    if not token:
        # Si no vino en dev_token, recalculamos con el hash
        token = "token-manual-de-prueba-12345"
        signup.token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        world.db.commit()

    # 2. Verificar alta
    res_verify = world.client.post("/api/v1/public/signup/verify", json={"token": token})
    assert res_verify.status_code == 200
    verify_data = res_verify.json()["data"]

    tenant_id = uuid.UUID(verify_data["tenant_id"])
    assert verify_data["slug"] == "alta-autoservicio-moda"
    assert verify_data["plan_code"] == "PROFESIONAL"
    assert verify_data["trial_days"] == 14

    # 3. Validar estado de la empresa
    tenant = world.db.get(TenantModel, tenant_id)
    assert tenant is not None
    assert tenant.status == "ACTIVA"
    assert tenant.contact_email == email

    # 4. Validar administrador
    admin = world.db.scalar(select(UserModel).where(UserModel.tenant_id == tenant_id))
    assert admin is not None
    assert admin.email == email
    assert admin.is_verified is True
    assert any(r.code == "admin" for r in admin.roles)

    # 5. Validar sucursal y caja inicial
    branch = world.db.scalar(select(BranchModel).where(BranchModel.tenant_id == tenant_id))
    assert branch is not None
    assert branch.code == "SUC-01"
    assert branch.name == "Casa Matriz"

    cash_point = world.db.scalar(select(CashPointModel).where(CashPointModel.tenant_id == tenant_id))
    assert cash_point is not None

    ub = world.db.scalar(select(UserBranchModel).where(UserBranchModel.tenant_id == tenant_id))
    assert ub is not None
    assert ub.user_id == admin.id
    assert ub.branch_id == branch.id

    # 6. Validar suscripción de prueba de 14 días
    sub = world.db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id == tenant_id))
    assert sub is not None
    assert sub.status == "ACTIVA"
    today = date.today()
    assert sub.start_date == today
    assert sub.end_date == today + timedelta(days=14)

    # 7. Validar aceptación legal registrada
    acceptances = world.db.scalars(
        select(LegalAcceptanceModel).where(LegalAcceptanceModel.user_id == admin.id)
    ).all()
    assert len(acceptances) == 2
    doc_codes = {a.document_code for a in acceptances}
    assert doc_codes == {"terms", "privacy"}


def test_token_usado_o_vencido_error(world):
    """Caso obligatorio 2: Token usado o vencido produce error 400."""
    _ensure_legal_docs_and_plan(world.db)

    # 1. Token inexistente
    res_fake = world.client.post("/api/v1/public/signup/verify", json={"token": "token-totalmente-inexistente"})
    assert res_fake.status_code == 400
    assert "no es válido" in res_fake.text

    # 2. Token vencido
    raw_token_expired = "token-expirado-12345678"
    token_hash = hashlib.sha256(raw_token_expired.encode("utf-8")).hexdigest()
    signup_expired = TenantSignupModel(
        id=uuid.uuid4(),
        email="expirado@fashionstore.test",
        company_name="Empresa Vencida",
        slug="empresa-vencida",
        password_hash="fake-hash",
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    world.db.add(signup_expired)
    world.db.commit()

    res_expired = world.client.post("/api/v1/public/signup/verify", json={"token": raw_token_expired})
    assert res_expired.status_code == 400
    assert "ha expirado" in res_expired.text

    # 3. Token ya usado
    raw_token_used = "token-usado-12345678"
    used_hash = hashlib.sha256(raw_token_used.encode("utf-8")).hexdigest()
    signup_used = TenantSignupModel(
        id=uuid.uuid4(),
        email="ya_usado@fashionstore.test",
        company_name="Empresa Usada",
        slug="empresa-usada",
        password_hash="fake-hash",
        token_hash=used_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=5),
        verified_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    world.db.add(signup_used)
    world.db.commit()

    res_used = world.client.post("/api/v1/public/signup/verify", json={"token": raw_token_used})
    assert res_used.status_code == 400
    assert "ya fue utilizado" in res_used.text


def test_signup_disabled_flag(world):
    """Requisito: SIGNUP_ENABLED=false retorna 404."""
    _ensure_legal_docs_and_plan(world.db)
    os.environ["SIGNUP_ENABLED"] = "false"
    try:
        res = world.client.post("/api/v1/public/signup", json={
            "company_name": "Tienda Apagada",
            "email": "apagado@test.com",
            "password": "Password123!",
            "accept_terms": True,
            "accept_privacy": True,
        })
        assert res.status_code == 404
    finally:
        os.environ.pop("SIGNUP_ENABLED", None)
