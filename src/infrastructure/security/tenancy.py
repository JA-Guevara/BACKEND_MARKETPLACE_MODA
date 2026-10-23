from dataclasses import dataclass
from typing import Annotated
from uuid import UUID
from fastapi import Depends, Header
from sqlalchemy.orm import Session
from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user, get_optional_user
from src.infrastructure.database.session import get_db
from src.infrastructure.config.settings import settings
from src.plataforma_saas.application.plan_guard import PlanGuard
from src.plataforma_saas.domain.exceptions import TenantInactiveError, TenantNotFoundError, TenantRequiredError
from src.plataforma_saas.infrastructure.repositories.saas_repository import SaasRepository


@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    user: UserModel


def get_tenant_context(user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)) -> TenantContext:
    if user.tenant_id is None:
        raise TenantRequiredError()
    tenant = SaasRepository(db).get_tenant(user.tenant_id)
    if tenant is None:
        raise TenantNotFoundError()
    if tenant.status != "ACTIVA":
        raise TenantInactiveError()
    return TenantContext(tenant.id, user)


TenantScope = Annotated[TenantContext, Depends(get_tenant_context)]


def get_public_tenant_id(x_tenant_slug: str | None = Header(default=None, alias="X-Tenant-Slug"),
                         user: UserModel | None = Depends(get_optional_user), db: Session = Depends(get_db)) -> UUID:
    repository = SaasRepository(db)
    tenant = repository.get_tenant(user.tenant_id) if user and user.tenant_id else repository.find_tenant_by_slug(x_tenant_slug or settings.default_tenant_slug)
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
