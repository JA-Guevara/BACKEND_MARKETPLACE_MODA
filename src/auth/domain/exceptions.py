from src.shared.exceptions.domain_exception import AuthenticationError, ConflictError


class InvalidCredentialsError(AuthenticationError):
    def __init__(self) -> None:
        super().__init__("Correo o contrasena incorrectos.")


class AccountLockedError(AuthenticationError):
    code = "account_locked"


class InactiveAccountError(AuthenticationError):
    code = "account_inactive"


class EmailAlreadyExistsError(ConflictError):
    def __init__(self) -> None:
        super().__init__("El correo electronico ya esta registrado.")
