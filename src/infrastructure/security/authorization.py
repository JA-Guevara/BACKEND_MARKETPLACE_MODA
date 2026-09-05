from collections.abc import Callable

from fastapi import Depends

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.shared.exceptions.domain_exception import AuthorizationError


def get_permission_codes(user: UserModel) -> set[str]:
    return {
        permission.code
        for role in user.roles
        if role.is_active
        for permission in role.permissions
        if permission.is_active
    }


def require_permissions(*required: str) -> Callable:
    def dependency(user: UserModel = Depends(get_current_user)) -> UserModel:
        granted = get_permission_codes(user)
        missing = set(required) - granted
        if missing:
            raise AuthorizationError(
                "No tiene permisos para realizar esta operacion.",
                details={"required": sorted(missing)},
            )
        return user

    return dependency
