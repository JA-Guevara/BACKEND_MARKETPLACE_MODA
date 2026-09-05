from src.auth.application.services.auth_service import AuthService


class RequestEmailVerification:
    def __init__(self, service: AuthService) -> None:
        self.service = service

    def execute(self, email: str) -> None:
        self.service.resend_verification(email)
