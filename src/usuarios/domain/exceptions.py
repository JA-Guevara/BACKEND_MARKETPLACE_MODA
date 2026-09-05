from src.shared.exceptions.domain_exception import ConflictError, NotFoundError


class UsuarioNoEncontradoError(NotFoundError):
    pass


class UsuarioDuplicadoError(ConflictError):
    pass
