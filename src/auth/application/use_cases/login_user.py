from src.auth.application.services.auth_service import AuthService


class LoginUser:
    def __init__(self, service: AuthService) -> None:
        self.service = service

    def execute(self, email: str, password: str, *, ip_address: str | None = None, user_agent: str | None = None):
        return self.service.login(email, password, ip_address=ip_address, user_agent=user_agent)
