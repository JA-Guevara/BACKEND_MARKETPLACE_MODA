from collections.abc import Callable

from fastapi import Depends

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.security.access_context import AccessContext, get_access_context, get_permission_codes
from src.plataforma_saas.domain.exceptions import PlatformScopeOnlyError
from src.shared.exceptions.domain_exception import AuthorizationError


def require_permissions(*required: str) -> Callable:
    def dependency(ctx: AccessContext = Depends(get_access_context)) -> UserModel:
        missing = set(required) - ctx.permissions
        if missing:
            raise AuthorizationError(
                "No tiene permisos para realizar esta operacion.",
                details={"required": sorted(missing)},
            )
        return ctx.user

    return dependency


def require_platform_permissions(*required: str) -> Callable:
    """La administración global exige cuenta de plataforma además del permiso."""
    def dependency(ctx: AccessContext = Depends(get_access_context)) -> UserModel:
        if ctx.is_support:
            raise PlatformScopeOnlyError()
        if not ctx.is_platform:
            raise AuthorizationError("Esta operación requiere un administrador de plataforma.")
        missing = set(required) - ctx.permissions
        if missing:
            raise AuthorizationError(
                "No tiene permisos para realizar esta operacion.",
                details={"required": sorted(missing)},
            )
        return ctx.user

    return dependency


def require_access(*required: str) -> Callable[..., AccessContext]:
    """Variante que devuelve el AccessContext completo."""
    def dependency(ctx: AccessContext = Depends(get_access_context)) -> AccessContext:
        missing = set(required) - ctx.permissions
        if missing:
            raise AuthorizationError(
                "No tiene permisos para realizar esta operacion.",
                details={"required": sorted(missing)},
            )
        return ctx

    return dependency
