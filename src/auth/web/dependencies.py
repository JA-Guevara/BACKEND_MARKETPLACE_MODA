import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.persistence.repositories.user_repository import UserRepository
from src.auth.infrastructure.security.jwt_service import JWTService
from src.infrastructure.database.session import get_db
from src.shared.context.audit_context import set_audit_actor
from src.shared.exceptions.domain_exception import AuthenticationError


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> UserModel:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Debe iniciar sesion.")
    payload = JWTService().decode(credentials.credentials, "access")
    try:
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, TypeError) as exc:
        raise AuthenticationError("Token invalido.") from exc
    user = UserRepository(db).get_by_id(user_id)
    if not user or not user.is_active:
        raise AuthenticationError("La cuenta no esta disponible.")
    set_audit_actor(user.id)
    return user
