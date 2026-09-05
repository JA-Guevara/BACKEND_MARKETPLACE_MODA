from src.auth.application.services.auth_service import AuthService


class ResetPassword:
    def __init__(self, service: AuthService) -> None:
        self.service = service

    def execute(self, token: str, new_password: str) -> None:
        self.service.reset_password(token, new_password)
