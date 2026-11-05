from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.security.jwt_service import JWTService
from src.auth.web.dependencies import bearer_scheme, get_current_user
from src.infrastructure.database.session import get_db
from src.plataforma_saas.application.entitlement_service import EntitlementService
from src.plataforma_saas.domain.exceptions import (
    SupportReadOnlyError,
    SupportSessionExpiredError,
    TenantInactiveError,
)
from src.plataforma_saas.infrastructure.models.support_session import SupportSessionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.shared.context.audit_context import set_audit_actor, set_audit_scope


READ_ONLY_ALLOWED_POST_PATHS = (
    "/analytics/assistant/interpret",
    "/analytics/reports/export",
)


def is_platform_account(user: UserModel) -> bool:
    return user.tenant_id is None and any(
        getattr(role, "tenant_id", None) is None
        and (role.code == "platform_admin" or getattr(role, "audience", "TENANT") == "PLATFORM")
        and getattr(role, "is_active", True)
        for role in user.roles
    )


@dataclass(frozen=True)
class AccessContext:
    user: UserModel
    tenant_id: UUID | None
    support_session_id: UUID | None
    permissions: frozenset[str]
    read_only: bool = False

    @property
    def is_support(self) -> bool:
        return self.support_session_id is not None

    @property
    def is_platform(self) -> bool:
        return not self.is_support and is_platform_account(self.user)


def tenant_scope_permissions(db: Session) -> frozenset[str]:
    stmt = select(PermissionModel.code).where(
        PermissionModel.scope == "tenant",
        PermissionModel.is_active.is_(True),
    )
    return frozenset(db.scalars(stmt).all())


def get_permission_codes(user: UserModel) -> frozenset[str]:
    return frozenset(
        permission.code
        for role in user.roles
        if getattr(role, "is_active", True)
        for permission in role.permissions
        if getattr(permission, "is_active", True)
    )


def get_access_context(
    request: Request,
    user: UserModel = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AccessContext:
    payload = None
    read_only = False
    if credentials and credentials.scheme.lower() == "bearer":
        try:
            payload = JWTService().decode(credentials.credentials, "access")
        except Exception:
            payload = None

    # 1. Sesión de soporte RFC 8693
    if payload and "ssid" in payload and payload["ssid"]:
        try:
            ssid = UUID(str(payload["ssid"]))
        except (ValueError, TypeError) as exc:
            raise SupportSessionExpiredError("Sesión de soporte inválida.") from exc

        session = db.get(SupportSessionModel, ssid)
        now = datetime.now(timezone.utc)
        if not session or not session.is_active(now) or session.platform_user_id != user.id:
            raise SupportSessionExpiredError()

        try:
            tenant_id = UUID(str(payload["tid"]))
        except (ValueError, TypeError, KeyError) as exc:
            raise SupportSessionExpiredError("Token de soporte sin tenant válido.") from exc

        tenant = db.get(TenantModel, tenant_id)
        if tenant is None or tenant.status != "ACTIVA":
            raise TenantInactiveError()

        support_session_id = ssid
        read_only = bool(payload.get("ro", False)) or (getattr(session, "mode", "WRITE") == "READ_ONLY")
        raw_perms = tenant_scope_permissions(db)
        permissions = EntitlementService(db).filtrar_permisos(tenant_id, raw_perms)

    # 2. Sesión estándar o test con user override
    else:
        tenant_id = user.tenant_id
        support_session_id = None
        read_only = False
        raw_perms = get_permission_codes(user)
        if tenant_id is not None:
            permissions = EntitlementService(db).filtrar_permisos(tenant_id, raw_perms)
        else:
            permissions = raw_perms

    # Validación de solo lectura para sesiones de soporte
    if read_only and request.method not in {"GET", "HEAD", "OPTIONS"}:
        path = request.url.path
        if request.method != "POST" or not any(path.endswith(endpoint) for endpoint in READ_ONLY_ALLOWED_POST_PATHS):
            raise SupportReadOnlyError("Estás en modo solo lectura.")

    set_audit_actor(user.id)
    set_audit_scope(tenant_id, support_session_id)
    request.state.tenant_id = str(tenant_id) if tenant_id is not None else None
    request.state.actor_id = str(user.id)

    return AccessContext(
        user=user,
        tenant_id=tenant_id,
        support_session_id=support_session_id,
        permissions=permissions,
        read_only=read_only,
    )
