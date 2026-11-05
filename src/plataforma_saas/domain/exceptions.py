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
    def __init__(self, message: str = "Tu plan no incluye esta funcionalidad.", *, details=None):
        super().__init__(message, details=details)


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


class SupportReadOnlyError(AuthorizationError):
    code = "support_read_only"
    def __init__(self, message: str = "Estás en modo solo lectura."):
        super().__init__(message)


class ModuleInBetaError(ConflictError):
    code = "module_in_beta"
    def __init__(self, message: str = "Un módulo beta no se agrega a un plan."):
        super().__init__(message)


class ModuleNotReviewedError(ConflictError):
    code = "module_not_reviewed"
    def __init__(self, message: str = "El módulo requiere una vista previa en la empresa demo antes de pasar a disponible (GA)."):
        super().__init__(message)


class ModuleRetiredError(ConflictError):
    code = "module_retired"
    def __init__(self, message: str = "Un módulo retirado no puede reactivarse."):
        super().__init__(message)


class TemplateImpactConfirmationError(ConflictError):
    code = "impact_confirmation_required"
    def __init__(self, message: str | dict = "Se requiere confirmación de impacto para actualizar la plantilla.", *, details=None):
        if isinstance(message, dict):
            details = message
            message = "Se requiere confirmación de impacto para actualizar la plantilla."
        super().__init__(message, details=details)


class SandboxOnlyError(ConflictError):
    code = "sandbox_only"
    def __init__(self, message: str = "Esta operación solo está disponible para la empresa demo."):
        super().__init__(message)


class RoleTenantMismatchError(ValidationError):
    code = "role_tenant_mismatch"
    def __init__(self, message: str = "El rol no pertenece a la misma empresa del usuario."):
        super().__init__(message)


class StoreNotPublishedError(NotFoundError):
    code = "store_not_published"
    def __init__(self, message: str = "La tienda no está publicada o no está disponible.", *, details=None):
        super().__init__(message, details=details)


class StoreAccountMismatchError(ConflictError):
    code = "store_account_mismatch"
    def __init__(self, message: str = "Tu cuenta pertenece a otra tienda.", *, details=None):
        super().__init__(message, details=details)


class PublishRequirementsError(ConflictError):
    code = "publish_requirements"
    def __init__(self, missing: list[str], message: str = "La tienda no cumple los requisitos para publicarse."):
        super().__init__(message, details={"missing": missing})


class InvalidBrandColorError(ValidationError):
    code = "invalid_brand_color"
    def __init__(self, message: str = "El color de marca no es válido o no cumple con el contraste mínimo."):
        super().__init__(message)


class UpgradeRequestOpenError(ConflictError):
    code = "upgrade_request_open"
    def __init__(self, message: str = "Ya existe una solicitud abierta para este tipo."):
        super().__init__(message)


class SupportRequestExpiredError(ConflictError):
    status_code = 410
    code = "support_request_expired"

    def __init__(self, message: str = "La solicitud de soporte ha expirado tras 10 minutos."):
        super().__init__(message)


class SupportRejectedError(AuthorizationError):
    status_code = 403
    code = "support_rejected"

    def __init__(self, message: str = "La empresa rechazó la solicitud de soporte."):
        super().__init__(message)


class SubscriptionReadOnlyError(AuthorizationError):
    status_code = 403
    code = "subscription_read_only"

    def __init__(self, message: str = "La suscripción está en modo solo lectura: las escrituras no están permitidas."):
        super().__init__(message)
