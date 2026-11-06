from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import bearer_scheme, get_optional_user
from src.infrastructure.config.settings import settings
from src.infrastructure.database.session import get_db, is_rls_enabled, set_rls_context
from src.infrastructure.security.access_context import AccessContext, get_access_context, is_platform_account
from src.plataforma_saas.application.plan_guard import PlanGuard
from src.plataforma_saas.domain.exceptions import (
    StoreAccountMismatchError,
    StoreNotPublishedError,
    TenantInactiveError,
    TenantNotFoundError,
    TenantRequiredError,
)
from src.plataforma_saas.infrastructure.repositories.saas_repository import SaasRepository
from src.shared.context.audit_context import get_audit_scope


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


def _puede_previsualizar(tenant, user: UserModel | None, support_tenant_id: UUID | None) -> bool:
    if user is None:
        return False
    if support_tenant_id is not None:
        return support_tenant_id == tenant.id
    return user.tenant_id == tenant.id or is_platform_account(user)


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

    support_tenant_id, support_session_id = get_audit_scope()
    if user is None or support_session_id is None:
        support_tenant_id = None
    if tenant is None and not x_tenant_slug and support_tenant_id is not None:
        tenant = repository.get_tenant(support_tenant_id)

    # 3. Si no viene cabecera y el usuario autenticado tiene empresa
    if tenant is None and not x_tenant_slug and user and user.tenant_id:
        tenant = repository.get_tenant(user.tenant_id)

    # 4. Fallback a tienda por defecto si no vino cabecera
    if tenant is None and not x_tenant_slug:
        tenant = repository.find_tenant_by_slug(settings.default_tenant_slug)

    if tenant is None:
        raise TenantNotFoundError()
    if tenant.status != "ACTIVA":
        raise TenantInactiveError()
    if support_tenant_id is not None and tenant.id != support_tenant_id:
        raise StoreAccountMismatchError()

    # Verificación de publicación (RS-3):
    is_pub = getattr(tenant, "is_published", True)
    if not is_pub:
        if not _puede_previsualizar(tenant, user, support_tenant_id):
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
