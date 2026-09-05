class AppException(Exception):
    status_code = 400
    code = "application_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
