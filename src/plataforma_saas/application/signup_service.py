from datetime import date, datetime, timedelta, timezone
import hashlib
import os
import re
import secrets
import unicodedata
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.roles.infrastructure.persistence.models.role import RoleModel
from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.security.password_hasher import PasswordHasher
from src.inventario_sucursales.infrastructure.models.organization import (
    BranchModel,
    CashPointModel,
    CityModel,
    UserBranchModel,
)
from src.plataforma_saas.infrastructure.models.plan import PlanModel
from src.plataforma_saas.infrastructure.models.signup_legal import (
    LegalAcceptanceModel,
    LegalDocumentModel,
    TenantSignupModel,
)
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.shared.exceptions.domain_exception import NotFoundError


RESERVED_SLUGS = {
    "admin",
    "api",
    "tienda",
    "plataforma",
    "platform",
    "public",
    "auth",
    "static",
    "assets",
    "dashboard",
    "superadmin",
    "billing",
    "soporte",
    "login",
    "register",
    "signup",
    "root",
    "app",
    "checkout",
    "store",
    "docs",
}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


class SignupRequest(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=150)
    slug: str | None = Field(None, max_length=60)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    first_name: str | None = Field("Administrador", max_length=80)
    last_name: str | None = Field("Empresa", max_length=80)
    accept_terms: bool = True
    accept_privacy: bool = True


class VerifyRequest(BaseModel):
    token: str = Field(..., min_length=10)


def signup_habilitado() -> bool:
    """Alta pública cerrada por defecto: solo SIGNUP_ENABLED=true (o 1/yes/on) la abre."""
    return os.getenv("SIGNUP_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


class SignupDisabledError(NotFoundError):
    status_code = 404
    code = "signup_disabled"

    def __init__(self, message: str = "El registro de tiendas está cerrado por ahora.") -> None:
        super().__init__(message)


def exigir_signup_habilitado() -> None:
    if not signup_habilitado():
        raise SignupDisabledError()


class SignupService:
    def __init__(self, db: Session):
        self.db = db
        self.passwords = PasswordHasher()

    def is_signup_enabled(self) -> bool:
        return signup_habilitado()

    def slug_disponible(self, name_or_slug: str) -> tuple[str, bool, str]:
        slug = slugify(name_or_slug or "")
        if not slug or len(slug) < 3:
            return slug, False, "El identificador debe tener al menos 3 caracteres."
        if slug in RESERVED_SLUGS:
            return slug, False, "El identificador está reservado para el sistema."
        # Verificar en base de datos si existe alguna empresa con este slug
        existing = self.db.scalar(select(TenantModel.id).where(TenantModel.slug == slug))
        if existing:
            return slug, False, "El identificador ya está en uso por otra tienda."
        return slug, True, "Disponible"

    def solicitar(self, data: SignupRequest, client_ip: str | None = None) -> dict:
        if not self.is_signup_enabled():
            raise SignupDisabledError()

        if not data.accept_terms or not data.accept_privacy:
            raise HTTPException(
                status_code=400,
                detail="Debes aceptar los Términos y Condiciones y la Política de Privacidad.",
            )

        target_slug = data.slug or data.company_name
        slug, disponible, motivo = self.slug_disponible(target_slug)
        if not disponible:
            raise HTTPException(status_code=400, detail=f"Identificador no disponible: {motivo}")

        email_clean = str(data.email).strip().lower()

        # Comprobar si el correo ya existe en usuarios o empresas (no revela cuentas)
        user_exists = self.db.scalar(
            select(UserModel.id).where(UserModel.email == email_clean, UserModel.deleted_at.is_(None))
        )
        tenant_exists = self.db.scalar(
            select(TenantModel.id).where(TenantModel.contact_email == email_clean)
        )

        generic_response = {
            "message": "Si el correo es válido, recibirás instrucciones de activación.",
            "email": email_clean,
        }

        if user_exists or tenant_exists:
            # Responde igual sin guardar solicitud ni revelar cuentas existentes
            return generic_response

        # Generar token seguro
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        pwd_hash = self.passwords.hash(data.password)

        signup = TenantSignupModel(
            id=uuid.uuid4(),
            email=email_clean,
            company_name=data.company_name.strip(),
            slug=slug,
            password_hash=pwd_hash,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        self.db.add(signup)
        self.db.commit()

        # En ambiente de prueba o local podemos adjuntar dev_token para facilitar pruebas automatizadas
        if os.getenv("APP_ENV") in ("local", "test") or os.getenv("TESTING") == "1":
            generic_response["dev_token"] = raw_token

        return generic_response

    def verificar(self, raw_token: str, client_ip: str | None = None) -> dict:
        if not self.is_signup_enabled():
            raise SignupDisabledError()

        token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
        signup = self.db.scalar(
            select(TenantSignupModel).where(TenantSignupModel.token_hash == token_hash)
        )

        if not signup:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "signup_token_invalid_or_expired",
                    "message": "El enlace de verificación no es válido o ya expiró.",
                },
            )

        if signup.verified_at is not None:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "signup_token_already_used",
                    "message": "El enlace de verificación ya fue utilizado.",
                },
            )

        now = datetime.now(timezone.utc)
        expires_at = signup.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at < now:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "signup_token_invalid_or_expired",
                    "message": "El enlace de verificación ha expirado.",
                },
            )

        # 1. Crear Tenant
        chosen_slug = signup.slug
        if self.db.scalar(select(TenantModel.id).where(TenantModel.slug == chosen_slug)):
            chosen_slug = f"{chosen_slug}-{secrets.randbelow(1000)}"

        tax_id = f"NIT-{secrets.randbelow(89999999) + 10000000}"
        tenant = TenantModel(
            id=uuid.uuid4(),
            legal_name=signup.company_name,
            trade_name=signup.company_name,
            tax_id=tax_id,
            slug=chosen_slug,
            contact_email=signup.email,
            status="ACTIVA",
            is_sandbox=False,
            support_access_mode="require_approval",
        )
        self.db.add(tenant)
        self.db.flush()

        # 2. Asignar rol de admin
        admin_role = self.db.scalar(select(RoleModel).where(RoleModel.code == "admin"))
        if not admin_role:
            # Crear rol admin si no estuviera
            admin_role = RoleModel(code="admin", name="Administrador", description="Administrador de empresa", scope="tenant")
            self.db.add(admin_role)
            self.db.flush()

        admin_user = UserModel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            email=signup.email,
            first_name="Admin",
            last_name=signup.company_name,
            password_hash=signup.password_hash,
            roles=[admin_role],
            is_verified=True,
        )
        self.db.add(admin_user)
        self.db.flush()

        # 3. Sucursal inicial y caja
        city = self.db.scalar(select(CityModel))
        if not city:
            city = CityModel(id=uuid.uuid4(), name="Santa Cruz", code="SCZ")
            self.db.add(city)
            self.db.flush()

        branch = BranchModel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            code="SUC-01",
            name="Casa Matriz",
            city_id=city.id,
            address="Av. Principal 100",
            is_active=True,
        )
        self.db.add(branch)
        self.db.flush()

        cash_point = CashPointModel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            branch_id=branch.id,
            code="CAJA-01",
            name="Caja Principal",
            is_active=True,
        )
        self.db.add(cash_point)

        user_branch = UserBranchModel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            user_id=admin_user.id,
            branch_id=branch.id,
            is_default=True,
        )
        self.db.add(user_branch)

        # 4. Suscripción de prueba de 14 días del plan Profesional (o estándar)
        plan = self.db.scalar(
            select(PlanModel).where(PlanModel.code == "PROFESIONAL", PlanModel.is_active == True)  # noqa: E712
        )
        if not plan:
            plan = self.db.scalar(select(PlanModel).where(PlanModel.is_active == True))  # noqa: E712
        if not plan:
            plan = PlanModel(
                code="PROFESIONAL",
                name="Plan Profesional",
                description="Plan completo con prueba gratuita",
                reference_price=690.0,
                duration_days=30,
                max_users=10,
                max_active_branches=5,
                is_active=True,
            )
            self.db.add(plan)
            self.db.flush()

        today = date.today()
        subscription = SubscriptionModel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            plan_id=plan.id,
            start_date=today,
            end_date=today + timedelta(days=14),
            status="ACTIVA",
            changed_by=admin_user.id,
            reason="Prueba gratuita autoservicio de 14 días",
        )
        self.db.add(subscription)

        # 5. Registrar aceptación legal de términos y privacidad
        ip_hash = hashlib.sha256(client_ip.encode("utf-8")).hexdigest() if client_ip else None
        for doc_code in ("terms", "privacy"):
            acceptance = LegalAcceptanceModel(
                id=uuid.uuid4(),
                user_id=admin_user.id,
                document_code=doc_code,
                version="1.0.0",
                accepted_at=now,
                ip_hash=ip_hash,
            )
            self.db.add(acceptance)

        # 6. Marcar signup verificado
        signup.verified_at = now
        signup.tenant_id = tenant.id

        self.db.commit()

        return {
            "tenant_id": str(tenant.id),
            "slug": tenant.slug,
            "user_id": str(admin_user.id),
            "plan_code": plan.code,
            "trial_days": 14,
            "message": "Empresa verificada y activada con prueba de 14 días.",
        }
