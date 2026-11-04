from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.security.jwt_service import JWTService
from src.auth.web.dependencies import bearer_scheme, get_current_user
from src.infrastructure.database.session import get_db
from src.plataforma_saas.domain.exceptions import SupportSessionExpiredError, TenantInactiveError
from src.plataforma_saas.infrastructure.models.support_session import SupportSessionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.shared.context.audit_context import set_audit_actor, set_audit_scope


@dataclass(frozen=True)
class AccessContext:
    user: UserModel
    tenant_id: UUID | None
    support_session_id: UUID | None
    permissions: frozenset[str]

    @property
    def is_support(self) -> bool:
        return self.support_session_id is not None

    @property
    def is_platform(self) -> bool:
        return (
            self.user.tenant_id is None
            and not self.is_support
            and any(
                r.code == "platform_admin" and getattr(r, "is_active", True)
                for r in self.user.roles
            )
        )


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
    user: UserModel = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AccessContext:
    payload = None
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
        permissions = tenant_scope_permissions(db)

    # 2. Sesión estándar o test con user override
    else:
        tenant_id = user.tenant_id
        support_session_id = None
        permissions = get_permission_codes(user)

    set_audit_actor(user.id)
    set_audit_scope(tenant_id, support_session_id)

    return AccessContext(
        user=user,
        tenant_id=tenant_id,
        support_session_id=support_session_id,
        permissions=permissions,
    )
