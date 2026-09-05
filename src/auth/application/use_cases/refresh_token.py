from src.auth.application.services.auth_service import AuthService


class RefreshAccessToken:
    def __init__(self, service: AuthService) -> None:
        self.service = service

    def execute(self, refresh_token: str, *, ip_address: str | None = None):
        return self.service.refresh(refresh_token, ip_address=ip_address)
