from src.shared.exceptions.domain_exception import ConflictError, ValidationError


class HorarioInvalidoError(ValidationError):
    pass


class TransicionInvalidaError(ConflictError):
    pass
