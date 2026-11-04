from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.security.jwt_service import JWTService
from src.auth.web.dependencies import bearer_scheme, get_optional_user
from src.infrastructure.config.settings import settings
from src.infrastructure.database.session import get_db
from src.infrastructure.security.access_context import AccessContext, get_access_context
from src.plataforma_saas.application.plan_guard import PlanGuard
from src.plataforma_saas.domain.exceptions import TenantInactiveError, TenantNotFoundError, TenantRequiredError
from src.plataforma_saas.infrastructure.repositories.saas_repository import SaasRepository


@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    user: UserModel
    support_session_id: UUID | None = None


def get_tenant_context(
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
    return TenantContext(tenant.id, ctx.user, ctx.support_session_id)


TenantScope = Annotated[TenantContext, Depends(get_tenant_context)]


def get_public_tenant_id(
    x_tenant_slug: str | None = Header(default=None, alias="X-Tenant-Slug"),
    user: UserModel | None = Depends(get_optional_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> UUID:
    repository = SaasRepository(db)

    # 1. Si hay token con tid (incluyendo soporte)
    if credentials and credentials.scheme.lower() == "bearer":
        try:
            payload = JWTService().decode(credentials.credentials, "access")
            if "tid" in payload and payload["tid"]:
                tenant_id = UUID(str(payload["tid"]))
                tenant = repository.get_tenant(tenant_id)
                if tenant:
                    if tenant.status != "ACTIVA":
                        raise TenantInactiveError()
                    return tenant.id
        except Exception:
            pass

    # 2. Si el usuario autenticado tiene empresa
    if user and user.tenant_id:
        tenant = repository.get_tenant(user.tenant_id)
    else:
        tenant = repository.find_tenant_by_slug(x_tenant_slug or settings.default_tenant_slug)

    if tenant is None:
        raise TenantNotFoundError()
    if tenant.status != "ACTIVA":
        raise TenantInactiveError()
    return tenant.id


def require_feature(code: str):
    def dependency(ctx: TenantScope, db: Session = Depends(get_db)) -> TenantContext:
        PlanGuard(db).exigir_funcion(ctx.tenant_id, code)
        return ctx

    return dependency
