from src.shared.exceptions.domain_exception import ConflictError, NotFoundError


class RoleNotFoundError(NotFoundError):
    pass


class ProtectedRoleError(ConflictError):
    pass
