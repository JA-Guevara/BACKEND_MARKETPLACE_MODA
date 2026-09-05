from src.shared.exceptions.base_exception import AppException


class NotFoundError(AppException):
    status_code = 404
    code = "not_found"


class ConflictError(AppException):
    status_code = 409
    code = "conflict"


class AuthenticationError(AppException):
    status_code = 401
    code = "authentication_failed"


class AuthorizationError(AppException):
    status_code = 403
    code = "permission_denied"


class ValidationError(AppException):
    status_code = 422
    code = "validation_error"
