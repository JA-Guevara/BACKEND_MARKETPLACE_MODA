from src.auth.application.services.auth_service import AuthService


class LogoutUser:
    def __init__(self, service: AuthService) -> None:
        self.service = service

    def execute(self, refresh_token: str, *, ip_address: str | None = None) -> None:
        self.service.logout(refresh_token, ip_address=ip_address)
