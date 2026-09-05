from src.auth.application.services.auth_service import AuthService


class VerifyEmail:
    def __init__(self, service: AuthService) -> None:
        self.service = service

    def execute(self, token: str) -> None:
        self.service.verify_email(token)
