from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.security.jwt_service import JWTService
from src.auth.web.dependencies import bearer_scheme, get_optional_user
from src.infrastructure.config.settings import settings
from src.infrastructure.database.session import get_db, is_rls_enabled, set_rls_context
from src.infrastructure.security.access_context import AccessContext, get_access_context
from src.plataforma_saas.application.plan_guard import PlanGuard
from src.plataforma_saas.domain.exceptions import (
    StoreAccountMismatchError,
    StoreNotPublishedError,
    TenantInactiveError,
    TenantNotFoundError,
    TenantRequiredError,
)
from src.plataforma_saas.infrastructure.repositories.saas_repository import SaasRepository


@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    user: UserModel
    support_session_id: UUID | None = None


def get_tenant_context(
    request: Request,
    ctx: AccessContext = Depends(get_access_context),
    db: Session = Depends(get_db),
) -> TenantContext:
    if ctx.tenant_id is None:
        raise TenantRequiredError()
    tenant = SaasRepository(db).get_tenant(ctx.tenant_id)
    if tenant is None:
        raise TenantNotFoundError()
    if tenant.status != "ACTIVA":
        raise TenantInactiveError()
    if request is not None:
        PlanGuard(db).verificar_escritura(ctx.tenant_id, path=request.url.path, method=request.method)
    return TenantContext(tenant.id, ctx.user, ctx.support_session_id)


TenantScope = Annotated[TenantContext, Depends(get_tenant_context)]


def _puede_previsualizar(tenant, user: UserModel | None, credentials: HTTPAuthorizationCredentials | None) -> bool:
    """Verifica si el usuario es personal de esa empresa o super admin para vista previa."""
    if user:
        if user.tenant_id is not None and str(user.tenant_id) == str(tenant.id):
            return True
        # Usuario de plataforma (sin tenant_id y con rol platform_admin)
        if user.tenant_id is None and any(getattr(r, "code", "") in ("platform_admin", "superadmin") or getattr(r, "name", "") in ("platform_admin", "superadmin", "Plataforma") for r in getattr(user, "roles", [])):
            return True

    if credentials and credentials.scheme.lower() == "bearer":
        try:
            payload = JWTService().decode(credentials.credentials, "access")
            tid = payload.get("tid")
            if tid and str(tid) == str(tenant.id):
                return True
            if payload.get("scope") == "support" or payload.get("ssid"):
                return True
            roles = payload.get("roles", [])
            if not tid and ("platform_admin" in roles or "superadmin" in roles):
                return True
        except Exception:
            pass
    return False


def get_public_tenant_id(
    x_tenant_slug: str | None = Header(default=None, alias="X-Tenant-Slug"),
    user: UserModel | None = Depends(get_optional_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> UUID:
    repository = SaasRepository(db)

    tenant = None
    # 1. Si viene cabecera X-Tenant-Slug, esa tienda tiene máxima prioridad
    if x_tenant_slug:
        tenant = repository.find_tenant_by_slug(x_tenant_slug)

    # 2. Si no viene cabecera pero hay token de soporte con claim 'tid'
    if tenant is None and credentials and credentials.scheme.lower() == "bearer":
        try:
            payload = JWTService().decode(credentials.credentials, "access")
            if "tid" in payload and payload["tid"]:
                tenant = repository.get_tenant(UUID(str(payload["tid"])))
        except Exception:
            pass

    # 3. Si no viene cabecera y el usuario autenticado tiene empresa
    if tenant is None and user and user.tenant_id:
        tenant = repository.get_tenant(user.tenant_id)

    # 4. Fallback a tienda por defecto si no vino cabecera
    if tenant is None and not x_tenant_slug:
        tenant = repository.find_tenant_by_slug(settings.default_tenant_slug)

    if tenant is None:
        raise TenantNotFoundError()
    if tenant.status != "ACTIVA":
        raise TenantInactiveError()

    # Verificación de publicación (RS-3):
    is_pub = getattr(tenant, "is_published", True)
    if not is_pub:
        if not _puede_previsualizar(tenant, user, credentials):
            raise StoreNotPublishedError()

    if is_rls_enabled():
        set_rls_context(db, tenant_id=tenant.id)
    return tenant.id


def require_store_account(
    slug_tenant_id: UUID,
    user: UserModel | None,
) -> None:
    """En operaciones de cliente (carrito, checkout, favoritos, reservas),

    exige que la cuenta del usuario pertenezca a la empresa de la tienda actual.
    """
    if user is not None and user.tenant_id is not None:
        if str(user.tenant_id) != str(slug_tenant_id):
            raise StoreAccountMismatchError()


def require_feature(code: str):
    def dependency(ctx: TenantScope, db: Session = Depends(get_db)) -> TenantContext:
        PlanGuard(db).exigir_funcion(ctx.tenant_id, code)
        return ctx

    return dependency
