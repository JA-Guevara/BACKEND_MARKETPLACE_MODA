from src.auth.application.services.auth_service import AuthService


class RequestPasswordReset:
    def __init__(self, service: AuthService) -> None:
        self.service = service

    def execute(self, email: str) -> None:
        self.service.request_password_reset(email)
