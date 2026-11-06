import uuid
from datetime import datetime, timezone

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.persistence.repositories.user_repository import UserRepository
from src.auth.infrastructure.security.jwt_service import JWTService
from src.infrastructure.database.session import get_db, set_rls_context
from src.plataforma_saas.domain.exceptions import SupportSessionExpiredError, TenantInactiveError
from src.plataforma_saas.infrastructure.models.support_session import SupportSessionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.shared.context.audit_context import set_audit_actor, set_audit_scope
from src.shared.exceptions.domain_exception import AuthenticationError

bearer_scheme = HTTPBearer(auto_error=False)


def validate_support_session(db: Session, user: UserModel, payload: dict) -> SupportSessionModel:
    try:
        session_id = uuid.UUID(str(payload["ssid"]))
        tenant_id = uuid.UUID(str(payload["tid"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise SupportSessionExpiredError() from exc
    session = db.get(SupportSessionModel, session_id)
    if (session is None or session.tenant_id != tenant_id or session.platform_user_id != user.id
            or not session.is_active(datetime.now(timezone.utc))):
        raise SupportSessionExpiredError()
    tenant = db.get(TenantModel, tenant_id)
    if tenant is None or tenant.status != "ACTIVA":
        raise TenantInactiveError()
    return session


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> UserModel:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Debe iniciar sesion.")
    payload = JWTService().decode(credentials.credentials, "access")
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise AuthenticationError("Token invalido.") from exc
    user = UserRepository(db).get_by_id(user_id)
    if not user or not user.is_active:
        raise AuthenticationError("La cuenta no esta disponible.")

    # Si no es token de soporte, validar que la empresa no haya cambiado
    if "ssid" not in payload:
        if "tid" in payload and payload["tid"] != (str(user.tenant_id) if user.tenant_id else None):
            raise AuthenticationError("La empresa de la sesión cambió. Inicie sesión nuevamente.")
        if user.tenant_id:
            tenant = db.get(TenantModel, user.tenant_id)
            if tenant is None or tenant.status != "ACTIVA":
                raise TenantInactiveError()

    set_audit_actor(user.id)
    if "ssid" in payload:
        from src.infrastructure.security.access_context import is_platform_account
        if not is_platform_account(user):
            raise SupportSessionExpiredError()
        support = validate_support_session(db, user, payload)
        set_audit_scope(support.tenant_id, support.id)
        set_rls_context(db, tenant_id=support.tenant_id)
    else:
        from src.infrastructure.security.access_context import is_platform_account
        set_rls_context(db, tenant_id=user.tenant_id, is_platform=is_platform_account(user))
    return user


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> UserModel | None:
    """Igual que get_current_user, pero devuelve None en vez de rechazar cuando
    no hay sesion, el token no es valido o una sesion de soporte ha vencido.
    Para endpoints publicos que se personalizan cuando el visitante esta logueado."""
    if not credentials or credentials.scheme.lower() != "bearer":
        return None
    try:
        return get_current_user(credentials, db)
    except AuthenticationError:
        return None
