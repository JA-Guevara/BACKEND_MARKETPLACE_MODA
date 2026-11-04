from src.shared.exceptions.domain_exception import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)


class TenantRequiredError(AuthorizationError):
    code = "tenant_required"
    def __init__(self): super().__init__("Esta operación requiere un usuario de empresa.")


class TenantInactiveError(AuthorizationError):
    code = "tenant_inactive"
    def __init__(self): super().__init__("La empresa está desactivada.")


class TenantNotFoundError(NotFoundError):
    code = "tenant_not_found"
    def __init__(self): super().__init__("Empresa no encontrada.")


class SubscriptionInactiveError(AuthorizationError):
    code = "subscription_inactive"
    def __init__(self): super().__init__("La suscripción no está activa: solo puedes consultar información.")


class FeatureNotInPlanError(AuthorizationError):
    code = "feature_not_in_plan"
    def __init__(self): super().__init__("Tu plan no incluye esta funcionalidad.")


class PlanLimitExceededError(ConflictError):
    code = "plan_limit_exceeded"
    def __init__(self, *, details=None): super().__init__("Alcanzaste el límite de tu plan.", details=details)


class TenantTaxIdTakenError(ConflictError):
    code = "tenant_tax_id_taken"
    def __init__(self): super().__init__("Ya existe una empresa con ese NIT.")


class TenantSlugTakenError(ConflictError):
    code = "tenant_slug_taken"
    def __init__(self): super().__init__("Ya existe una empresa con ese identificador.")


class PlanCodeTakenError(ConflictError):
    code = "plan_code_taken"
    def __init__(self): super().__init__("Ya existe un plan con ese código.")


class PlanLimitInvalidError(ValidationError):
    code = "plan_limit_invalid"
    def __init__(self): super().__init__("Los límites deben ser números positivos.")


class SupportSessionExpiredError(AuthenticationError):
    code = "support_session_expired"
    def __init__(self, message: str = "La sesión de soporte ha expirado o no es válida."):
        super().__init__(message)


class PlatformScopeOnlyError(AuthorizationError):
    code = "platform_scope_only"
    def __init__(self, message: str = "Esta operación solo está disponible en el alcance de plataforma."):
        super().__init__(message)


class SupportReasonInvalidError(ValidationError):
    code = "support_reason_invalid"
    def __init__(self, message: str = "El motivo de la sesión de soporte es inválido."):
        super().__init__(message)


class SupportLimitExceededError(ConflictError):
    code = "support_limit_exceeded"
    def __init__(self, message: str = "Límite de tiempo de soporte excedido o sesión no permitida."):
        super().__init__(message)


class SystemRoleLockedError(ConflictError):
    code = "system_role_locked"
    def __init__(self, message: str = "No se puede modificar un rol del sistema protegido."):
        super().__init__(message)


class PermissionOutOfScopeError(AuthorizationError):
    code = "permission_out_of_scope"
    def __init__(self, message: str = "El permiso está fuera del alcance de la operación."):
        super().__init__(message)


class LastPlatformAdminError(ConflictError):
    code = "last_platform_admin"
    def __init__(self, message: str = "No se puede eliminar o degradar al último administrador de plataforma."):
        super().__init__(message)
